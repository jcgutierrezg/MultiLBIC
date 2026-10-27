"""The laser board driver, against the simulated 2.0.0 firmware."""

import pytest

from multilbic.hardware.laser import LaserBoard, LaserBoardError
from multilbic.sim.fake_laser import FakeLaserBoard
from multilbic.sim.link import connect


@pytest.fixture
def rig(machine, clock):
    fake = FakeLaserBoard()
    board = LaserBoard(connect(fake, clock), machine, clock)
    board.open()
    yield board, fake, clock
    board.close()


def test_open_identifies_and_reads_settle(rig):
    board, _, _ = rig
    assert board.firmware == "MultiLBIC-Laser,2.0.0"
    assert board.settle_ms == 2000


def test_open_refuses_other_firmware(machine, clock):
    fake = FakeLaserBoard(firmware_id="Servo moved to: 90")
    board = LaserBoard(connect(fake, clock), machine, clock)
    with pytest.raises(LaserBoardError, match="not a MultiLBIC laser"):
        board.open()


def test_open_refuses_mismatched_angles(machine, clock):
    fake = FakeLaserBoard(angles=(150, 90, 30, 150, 90, 45))
    board = LaserBoard(connect(fake, clock), machine, clock)
    with pytest.raises(LaserBoardError, match="do not match"):
        board.open()


def test_select_and_off(rig):
    board, fake, _ = rig
    board.select(3)
    assert board.state().laser == 3
    assert board.state().servo_angle_deg == 30
    assert fake.active == 3
    board.off()
    assert board.state().laser == 0
    # LASER 0 no longer parks the servo.
    assert board.state().servo_angle_deg == 30


def test_settle_skipped_when_angle_unchanged(rig):
    board, _, clock = rig
    board.select(1)  # 90 -> 150: settles
    start = clock.now()
    board.select(4)  # also 150: no servo move, no settle
    assert clock.now() - start < 0.5
    start = clock.now()
    board.select(2)  # 150 -> 90: settles
    assert clock.now() - start == pytest.approx(2.0, abs=0.3)


def test_set_settle(rig):
    board, _, clock = rig
    board.set_settle(500)
    start = clock.now()
    board.select(3)
    assert clock.now() - start == pytest.approx(0.5, abs=0.2)


def test_refusals(rig):
    board, _, _ = rig
    with pytest.raises(LaserBoardError, match="BAD_VALUE"):
        board.set_settle(20000)
    with pytest.raises(LaserBoardError, match="BAD_LASER"):
        board.query("LASER 9")
    with pytest.raises(KeyError):
        board.select(7)  # refused before anything is sent


def test_timeout_puts_the_link_out_of_step(rig):
    board, fake, _ = rig
    fake.silent = True
    with pytest.raises(LaserBoardError, match="no reply"):
        board.state()
    with pytest.raises(LaserBoardError, match="resync"):
        board.state()
    fake.silent = False
    board.resync()
    assert board.state().laser == 0


def test_open_applies_the_configured_settle(machine, clock):
    # The firmware forgets a runtime settle on power-up; open() puts the
    # machine.toml value back whatever the board starts with.
    fake = FakeLaserBoard(settle_ms=500)
    board = LaserBoard(connect(fake, clock), machine, clock)
    board.open()
    assert machine.laser_board.settle_ms == 2000
    assert board.settle_ms == 2000
    assert fake.settle_ms == 2000


def test_open_leaves_a_matching_settle_alone(machine, clock):
    fake = FakeLaserBoard(settle_ms=2000)
    board = LaserBoard(connect(fake, clock), machine, clock)
    board.open()
    assert not [line for line in fake.received if line.startswith("SETTLE ")]


def dark_before_last_on(history, laser):
    """How long `laser` was off before it last came on, from the fake's
    history of (time, lit laser)."""
    went_off, gap, lit = None, None, 0
    for t, now in history:
        if lit == laser and now != laser:
            went_off = t
        if now == laser and lit != laser and went_off is not None:
            gap = t - went_off
        lit = now
    return gap


def test_a_laser_is_not_relit_too_soon(rig, machine):
    # Laser 1 relit within a second comes back at 40 % (bench, 2026-10-27).
    board, fake, clock = rig
    relight = machine.laser_board.relight_ms / 1000.0
    board.select(1)
    board.off()
    start = clock.now()
    board.select(1)  # same angle: no settle, so it waits instead
    assert clock.now() - start == pytest.approx(relight, abs=0.3)
    assert dark_before_last_on(fake.history, 1) >= relight - 0.05


def test_the_servo_settle_counts_towards_the_wait(rig, machine):
    board, fake, clock = rig
    relight = machine.laser_board.relight_ms / 1000.0
    board.set_settle(500)
    board.select(1)
    board.select(2)  # 150 -> 90: laser 1 dark for the 0.5 s settle
    start = clock.now()
    board.select(1)  # waits 2 s, then the 0.5 s settle: 3 s dark in all
    assert clock.now() - start == pytest.approx(relight - 0.5, abs=0.3)
    assert dark_before_last_on(fake.history, 1) >= relight - 0.05
    # With the full 2 s settle each way it is dark long enough already.
    board.set_settle(2000)
    board.select(2)
    start = clock.now()
    board.select(1)
    assert clock.now() - start == pytest.approx(2.0, abs=0.3)
    # Laser 2 was never off before: it came on without a wait.
    assert board.relight_wait_s(3) == 0.0


def test_selecting_the_laser_already_on_sends_nothing(rig):
    board, fake, clock = rig
    board.select(3)
    sent = len(fake.received)
    lit = len(fake.history)
    start = clock.now()
    board.select(3)
    assert len(fake.received) == sent and len(fake.history) == lit
    assert clock.now() - start < 0.1
    assert fake.active == 3


def test_open_reads_what_is_lit(machine, clock):
    fake = FakeLaserBoard()
    fake.active, fake.servo_angle = 2, 90
    board = LaserBoard(connect(fake, clock), machine, clock)
    board.open()
    sent = len(fake.received)
    board.select(2)  # on already, as the board said
    assert len(fake.received) == sent
