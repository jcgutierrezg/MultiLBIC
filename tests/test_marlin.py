"""The Marlin client, against the simulated Marlin over the same text."""

import threading

import pytest

from multilbic.hardware.marlin import (
    Marlin,
    MarlinCommandError,
    MarlinError,
    MarlinHalted,
    MarlinTimeout,
    MotionLimitError,
    checksum,
    parse_position,
)
from multilbic.sim.fake_marlin import FakeMarlin
from multilbic.sim.link import connect


@pytest.fixture
def rig(machine, clock):
    fake = FakeMarlin(machine)
    client = Marlin(connect(fake, clock), machine, clock)
    client.open()
    yield client, fake, clock
    client.close()


def test_checksum_matches_marlin():
    # XOR of every byte before '*', as in queue.cpp.
    body = "N1 G1 X1"
    expected = 0
    for byte in body.encode():
        expected ^= byte
    assert checksum(body) == expected


def test_parse_position_ignores_step_counts():
    line = "X:1.5000 Y:2.0000 Z:0.0000 A:17.5000 B:3.2500 Count X:600 Y:800"
    assert parse_position(line) == {
        "X": 1.5, "Y": 2.0, "Z": 0.0, "A": 17.5, "B": 3.25,
    }


def test_open_identifies_machine(rig):
    client, fake, _ = rig
    assert client.info.machine_type == "MultiLBIC"
    assert client.info.capabilities["EMERGENCY_PARSER"] == "1"
    assert client.advanced_ok
    # Absolute mode and no automatic position reports after open.
    assert "G90" in fake.executed and "M154 S0" in fake.executed


def test_open_refuses_another_machine(machine, clock):
    fake = FakeMarlin(machine, machine_type="Ender-3")
    client = Marlin(connect(fake, clock), machine, clock)
    with pytest.raises(MarlinError, match="wrong port"):
        client.open()
    client.close()


def test_lines_are_numbered_with_checksums(rig):
    client, _, _ = rig
    client.send("M117 hello")
    sent = [line for _, d, line in client.traffic if d == ">"]
    numbered = [s for s in sent if s.startswith("N")]
    assert numbered, sent
    for wire in numbered:
        body, _, given = wire.rpartition("*")
        assert int(given) == checksum(body)


def test_absolute_move_needs_homing(rig):
    client, _, _ = rig
    with pytest.raises(MarlinError, match="home first"):
        client.move_to(a=10.0, feed_mm_s=1.0)


def test_home_then_move_and_wait(rig):
    client, fake, clock = rig
    client.home()
    assert client.homed and client.position_trusted
    client.move_to(a=10.0, b=10.0, feed_mm_s=1.0)
    # M114 reports the destination straight away, while still moving.
    assert client.position()["A"] == pytest.approx(10.0)
    assert fake.moving()
    client.wait_idle(timeout=30)
    assert not fake.moving()
    assert fake.stage_position()["A"] == pytest.approx(10.0)


def test_wait_idle_survives_a_move_longer_than_its_timeout(rig):
    # A 30 mm A move at 2 mm/s takes 15 s; the timeout is 3 s of silence.
    # Keepalives every 2 s are what keep it alive. Homed, A reads 5.
    client, fake, clock = rig
    client.home()
    client.move_to(a=35.0, feed_mm_s=2.0)
    start = clock.now()
    client.wait_idle(timeout=3.0)
    assert clock.now() - start == pytest.approx(15.1, abs=0.5)


def test_overspeed_is_refused_not_clamped(rig):
    client, _, _ = rig
    client.home()
    with pytest.raises(MotionLimitError, match="A would move at 7.000"):
        client.move_to(a=10.0, feed_mm_s=7.0)  # above the 6 mm/s ceiling


def test_diagonal_feed_is_checked_per_axis(rig):
    client, _, _ = rig
    client.home()
    # Equal A and B travel: each axis sees feed/sqrt(2), so the diagonal
    # may run at 6 * sqrt(2) = 8.49 mm/s.
    client.move_to(a=5.0, b=5.0, feed_mm_s=8.4)
    with pytest.raises(MotionLimitError):
        client.move_to(a=10.0, b=10.0, feed_mm_s=8.6)


def test_out_of_safe_range_is_refused(rig):
    client, _, _ = rig
    client.home()
    with pytest.raises(MotionLimitError, match="outside 0.5..39.5"):
        client.move_to(b=39.8, feed_mm_s=1.0)


def test_open_turns_soft_endstops_off_and_sets_the_home_offset(rig):
    client, fake, _ = rig
    assert fake.home_offset == {"A": 5.0, "B": 5.0}
    client.home()
    position = client.position()
    assert (position["A"], position["B"]) == (5.0, 5.0)
    assert position["X"] == 0.0


def test_a_home_offset_that_does_not_take_refuses_to_move(rig):
    client, fake, _ = rig
    fake.home_offset = {}  # as if M206 worked the other way
    with pytest.raises(MarlinError, match="refusing to move"):
        client.home()
    with pytest.raises(MarlinError, match="not trusted"):
        client.move_to(a=10.0, feed_mm_s=1.0)


def test_jog_before_homing(rig):
    client, fake, _ = rig
    client.jog(da=1.0, feed_mm_s=1.0)
    client.wait_idle()
    assert fake.stage_position()["A"] == pytest.approx(1.0)


def test_unknown_command_raises(rig):
    client, _, _ = rig
    with pytest.raises(MarlinCommandError, match="Unknown command"):
        client.send("G999")
    # The connection is still in step afterwards.
    assert client.position()["X"] == 0.0


def test_corrupted_line_is_resent(rig):
    client, fake, _ = rig
    fake.corrupt_next_line = True
    reply = client.send("M117 resent")
    assert reply.ok.startswith("ok N")
    assert fake.executed.count("M117 resent") == 1


def test_timeout_then_late_ok_is_not_misattributed(rig):
    client, fake, _ = rig
    fake.drop_next_ok = True
    with pytest.raises(MarlinTimeout):
        client.send("M117 lost", timeout=0.5)
    # The next command gets its own ok, not a stale one.
    assert client.position()["A"] == 0.0


def test_silence_times_out(rig):
    client, fake, _ = rig
    fake.silent = True
    with pytest.raises(MarlinTimeout):
        client.send("M114", timeout=0.5)


def test_quickstop_interrupts_a_wait(rig):
    client, fake, clock = rig
    client.home()
    home = client.position()["A"]
    client.move_to(a=home + 30.0, feed_mm_s=2.0)  # 15 s
    results = {}

    def waiter():
        start = clock.now()
        client.wait_idle(timeout=5.0)
        results["elapsed"] = clock.now() - start

    thread = threading.Thread(target=waiter)
    thread.start()
    clock.sleep(2.0)
    client.quickstop()
    thread.join(timeout=5)
    assert results["elapsed"] < 5.0
    stopped = fake.stage_position()["A"]
    assert 2.0 < stopped - home < 6.0
    # The extra ok from the queued M410 is absorbed, and the position
    # reported is where the stage actually stopped.
    assert client.position()["A"] == pytest.approx(stopped, abs=1e-3)


def test_kill_halts_the_client(rig):
    client, _, _ = rig
    client._submit("M112", numbered=False)
    with pytest.raises(MarlinHalted):
        for _ in range(50):
            client.send("M114", timeout=0.5)


def test_restart_is_reported(rig):
    client, fake, _ = rig
    client.home()
    fake.inject_restart()
    with pytest.raises(MarlinError):
        for _ in range(50):
            client.send("M114", timeout=0.5)
    assert not client.position_trusted


def test_releasing_motors_untrusts_position(rig):
    client, _, _ = rig
    client.home()
    client.motors(False)
    with pytest.raises(MarlinError, match="home first"):
        client.move_to(a=1.0, feed_mm_s=1.0)


def test_settings_dump(rig):
    client, _, _ = rig
    lines = client.settings()
    assert any("M203" in line and "A6.00" in line for line in lines)


def test_move_right_after_quickstop_is_not_lost(rig):
    # Bench, 2026-10-20: for 1 s after M410 Marlin drops new moves while
    # answering ok and reporting their target as the position.
    client, fake, clock = rig
    client.home()
    client.move_to(a=20.0, feed_mm_s=2.0)
    clock.sleep(1.0)
    client.quickstop()
    client.move_to(a=5.0, feed_mm_s=2.0)  # immediately after the stop
    client.wait_idle(timeout=10.0)
    assert fake.dropped_moves == 0
    assert fake.stage_position()["A"] == pytest.approx(5.0)


def test_fake_drops_moves_during_the_lockout(rig):
    # The behaviour the client guards against, checked on the fake.
    client, fake, clock = rig
    client.home()
    client.move_to(a=20.0, feed_mm_s=2.0)
    clock.sleep(1.0)
    client.quickstop()
    client._settle_after_stop = False  # bypass the guard
    client.move_to(a=5.0, feed_mm_s=2.0)
    assert fake.dropped_moves == 1
    assert client.position()["A"] == pytest.approx(5.0)  # Marlin's claim
    assert fake.stage_position()["A"] != pytest.approx(5.0)
