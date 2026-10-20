"""The faults the simulators inject for the scan's tests: backlash,
reply latency, noise shaped like the bench's, and the ground truth."""

import pytest

from multilbic.hardware.marlin import Marlin
from multilbic.sim.fake_marlin import FakeMarlin
from multilbic.sim.fake_smu import FakeMiniSMU
from multilbic.sim.link import connect
from multilbic.sim.sample import SyntheticSample


def homed(machine, clock, **options):
    fake = FakeMarlin(machine, home_duration_s=0.1, **options)
    client = Marlin(connect(fake, clock), machine, clock)
    client.open()
    client.home()
    return client, fake


def test_backlash_lags_the_stage_on_a_reversal(machine, clock):
    client, fake = homed(machine, clock, backlash_mm={"A": 0.02})
    try:
        client.move_to(feed_mm_s=5.0, a=10.0)
        client.wait_idle()
        # Moving +A: the stage trails the motor by half the backlash.
        assert fake.motor_position()["A"] == pytest.approx(10.0)
        assert fake.stage_position()["A"] == pytest.approx(9.99)
        # Back 15 µm: the motor turns, the stage doesn't move.
        client.move_to(feed_mm_s=1.0, a=9.985)
        client.wait_idle()
        assert fake.stage_position()["A"] == pytest.approx(9.99)
        # Further back: now it follows, half the backlash ahead.
        client.move_to(feed_mm_s=1.0, a=9.5)
        client.wait_idle()
        assert fake.stage_position()["A"] == pytest.approx(9.51)
    finally:
        client.close()


def test_the_stage_path_is_kept_for_checking(machine, clock):
    client, fake = homed(machine, clock)
    try:
        client.move_to(feed_mm_s=2.0, a=4.0)
        start = clock.now()
        client.wait_idle()
        end = clock.now()
        client.move_to(feed_mm_s=2.0, a=0.0)
        client.wait_idle()
        # Long after, the first move can still be looked up.
        assert fake.past_stage_position(end + 0.001)["A"] == pytest.approx(4.0)
        middle = fake.past_stage_position((start + end) / 2)["A"]
        assert 0.5 < middle < 3.5
        assert fake.past_stage_position(0.0)["A"] == 0.0
    finally:
        client.close()


def test_replies_arrive_late_and_in_order(machine, clock):
    fake = FakeMarlin(machine)
    client = Marlin(connect(fake, clock, latency_s=0.05, jitter_s=0.02),
                    machine, clock)
    client.open()
    try:
        replies = [client.send("M114") for _ in range(5)]
        for reply in replies:
            assert reply.received_s - reply.sent_s >= 0.05
        received = [r.received_s for r in replies]
        assert received == sorted(received)
    finally:
        client.close()


def test_bench_shaped_noise_and_bursts(clock):
    fake = FakeMiniSMU(clock, mains_a=1e-8, drift_a=4e-8, burst_s=0.1)
    values = [fake.interference(t / 1000) for t in range(2000)]
    assert max(values) > 2e-8
    # Packets due inside a burst all reach the port at its end.
    assert fake._released(0.0101) == pytest.approx(0.1)
    assert fake._released(0.0999) == pytest.approx(0.1)
    assert fake._released(0.1001) == pytest.approx(0.2)


def test_true_time_inverts_the_stamp(clock):
    fake = FakeMiniSMU(clock, device_offset_ms=5000.0, drift_ppm=100.0)
    t = clock.now() + 12.345
    assert fake.true_time(fake.device_ms(t)) == pytest.approx(t, abs=1e-9)


def test_synthetic_edges_sit_at_the_half_way_point():
    sample = SyntheticSample.default(1.0, 0.3, cell_a=1e-6)
    left = sample.patches[0]
    v = (left.v0 + left.v1) / 2
    inside = sample.current(650, left.u0 + 0.05, v)
    at_edge = sample.current(650, left.u0, v)
    assert inside == pytest.approx(1e-6, rel=1e-6)
    assert at_edge == pytest.approx(inside / 2, rel=1e-6)
    # Fingers shade the cell completely.
    finger = sample.patches[2]
    middle = (finger.u0 + finger.u1) / 2
    assert sample.current(650, middle, v) < 0.05 * inside
