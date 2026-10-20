"""The scan's own motion model and the clock map."""


import numpy as np
import pytest

from multilbic.scan.timing import (
    ClockMap,
    ClockTracker,
    RowMotion,
    Trapezoid,
    axis_accel,
    fit_clock,
)
from multilbic.sim import motion
from multilbic.sim.motion import AxisLimits


@pytest.mark.parametrize(
    ("speed", "bench_model_s"),
    # docs/hardware.md, A speed trials: "Model, without the 0.1 s
    # first-move delay", for 20 mm at 50 mm/s².
    [(3.0, 6.73), (4.0, 5.08), (5.0, 4.10), (6.0, 3.45)],
)
def test_duration_matches_the_bench_table(speed, bench_model_s):
    assert Trapezoid(20.0, speed, 50.0).duration_s == pytest.approx(
        bench_model_s, abs=0.006
    )


def test_agrees_with_the_simulators_model():
    """Two separate implementations of Marlin's trapezoid: if they
    disagree, one of them is wrong."""
    rng = np.random.default_rng(1)
    limits = {"A": AxisLimits(6.0, 50.0)}
    for _ in range(50):
        distance = float(rng.uniform(0.001, 30.0))
        feed = float(rng.uniform(0.5, 6.0))
        block = motion.plan({"A": 0.0}, {"A": distance}, feed, limits,
                            100.0, 0.0)
        mine = Trapezoid(distance, feed, axis_accel(50.0))
        assert mine.duration_s == pytest.approx(block.duration, rel=1e-9)
        for t in np.linspace(0, block.duration, 7):
            assert float(mine.distance_at(t)) == pytest.approx(
                block.distance_at(t), abs=1e-9
            )


def test_short_move_is_a_triangle():
    move = Trapezoid(0.01, 6.0, 50.0)  # far too short to reach 6 mm/s
    t = move.duration_s
    assert t == pytest.approx(2 * np.sqrt(0.01 / 50.0))
    assert float(move.distance_at(t / 2)) == pytest.approx(0.005)
    assert float(move.distance_at(t)) == pytest.approx(0.01)


def test_row_motion_runs_backwards_on_reverse_rows():
    row = RowMotion.from_anchor(12.0, 10.0, 1.0, 50.0, end_s=100.0)
    assert row.direction == -1
    assert float(row.a_at(row.start_s)) == pytest.approx(12.0)
    assert float(row.a_at(100.0)) == pytest.approx(10.0)
    middle = (row.start_s + row.end_s) / 2
    assert float(row.a_at(middle)) == pytest.approx(11.0)
    # Before and after the move the stage is at rest at its ends.
    assert float(row.a_at(row.start_s - 1)) == pytest.approx(12.0)
    assert float(row.a_at(101.0)) == pytest.approx(10.0)


def _stream(offset_s, drift, seconds=60.0, rate=500.0, seed=0):
    """Stamps from a device clock, and host arrival times that are
    always later, by a random delivery delay."""
    rng = np.random.default_rng(seed)
    host_true = np.arange(0, seconds, 1 / rate)
    # device = (host - offset) / (1 + drift), whole milliseconds.
    device_ms = np.round((host_true - offset_s) / (1 + drift) * 1000)
    arrival = host_true + rng.exponential(0.003, host_true.size)
    return host_true, device_ms, arrival


def test_clock_map_recovers_offset_and_drift():
    host_true, device_ms, arrival = _stream(offset_s=-1234.5, drift=100e-6)
    clock = fit_clock(device_ms, arrival)
    mapped = clock.to_host(device_ms)
    # Within the stamps' whole-millisecond rounding.
    assert np.abs(mapped - host_true).max() < 0.0012
    assert clock.drift * 1e6 == pytest.approx(100, abs=20)


def test_a_starved_window_does_not_tilt_the_map():
    host_true, device_ms, arrival = _stream(offset_s=50.0, drift=0.0)
    # For one second near the end the host read nothing: everything in
    # it arrived 80 ms late. A least-squares line would tilt toward it.
    late = (host_true > 50) & (host_true < 51)
    arrival[late] += 0.08
    clock = fit_clock(device_ms, arrival)
    assert np.abs(clock.to_host(device_ms) - host_true).max() < 0.0012


def test_tracker_matches_a_single_fit():
    _, device_ms, arrival = _stream(offset_s=3.0, drift=-50e-6)
    tracker = ClockTracker()
    for chunk in np.array_split(np.arange(device_ms.size), 37):
        tracker.add(device_ms[chunk], arrival[chunk])
    assert tracker.fit() == fit_clock(device_ms, arrival)


def test_clock_map_round_trips_through_a_dict():
    clock = ClockMap(-12.5, 37e-6, 1000.0)
    again = ClockMap.from_dict(clock.as_dict())
    assert again.offset_s == clock.offset_s
    assert again.drift == pytest.approx(clock.drift)
    assert again.reference_s == clock.reference_s
