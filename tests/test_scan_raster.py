"""The row plan."""

import pytest

from multilbic.scan.geometry import SampleFrame
from multilbic.scan.raster import (
    MAX_STREAM_HZ,
    RasterError,
    ScanRequest,
    plan_raster,
)


def frame(width=10.0, height=1.0):
    return SampleFrame((5.0, 5.0), width, height)


def test_serpentine_rows(machine):
    plan = plan_raster(ScanRequest(frame(), 0.01, 0.1, 2.0), machine)
    assert len(plan.rows) == 10
    assert [row.forward for row in plan.rows[:4]] == [True, False, True, False]
    # Rows sit at the centres of the pixel rows.
    assert plan.rows[0].b_mm == pytest.approx(5.05)
    assert plan.rows[-1].b_mm == pytest.approx(5.95)
    first, second = plan.rows[0], plan.rows[1]
    # Run-up before the sample and run-out after it, both ways.
    assert first.a_from_mm == pytest.approx(5.0 - plan.run_up_mm)
    assert first.a_to_mm == pytest.approx(15.0 + plan.run_up_mm)
    assert second.a_from_mm == first.a_to_mm
    assert second.a_to_mm == first.a_from_mm


def test_one_direction_rows_all_go_forward(machine):
    plan = plan_raster(
        ScanRequest(frame(), 0.01, 0.1, 2.0, serpentine=False), machine
    )
    assert all(row.forward for row in plan.rows)


def test_run_up_covers_the_acceleration(machine):
    slow = plan_raster(ScanRequest(frame(), 0.01, 0.1, 1.0), machine)
    fast = plan_raster(ScanRequest(frame(), 0.01, 0.1, 5.0), machine)
    assert slow.run_up_mm == pytest.approx(0.1)  # the floor
    # 5 mm/s at 50 mm/s² takes 0.25 mm to reach.
    assert fast.run_up_mm > 0.25


def test_stream_rate_follows_the_pixel(machine):
    plan = plan_raster(ScanRequest(frame(), 0.01, 0.1, 2.0), machine)
    assert plan.stream_hz == pytest.approx(400)  # 2 per 10 µm at 2 mm/s
    assert plan.samples_per_pixel == pytest.approx(2.0)
    fine = plan_raster(ScanRequest(frame(), 0.003, 0.1, 2.0), machine)
    assert fine.stream_hz == MAX_STREAM_HZ
    assert fine.samples_per_pixel >= 1.0


def test_pixel_too_fine_for_the_speed(machine):
    with pytest.raises(RasterError, match="or slower"):
        plan_raster(ScanRequest(frame(), 0.001, 0.1, 5.0), machine)


def test_refuses_what_the_machine_cannot_do(machine):
    with pytest.raises(RasterError, match="speed"):
        plan_raster(ScanRequest(frame(), 0.01, 0.1, 7.0), machine)
    with pytest.raises(RasterError, match="microstep"):
        plan_raster(ScanRequest(frame(), 0.01, 0.0001, 2.0), machine)
    # 30 mm wide from A=5 runs past the 35 mm safe limit.
    with pytest.raises(RasterError, match="safe range"):
        plan_raster(ScanRequest(frame(width=30.0), 0.01, 0.1, 2.0), machine)


def test_estimate_scales_with_rows(machine):
    one = plan_raster(ScanRequest(frame(height=0.1), 0.01, 0.1, 2.0), machine)
    ten = plan_raster(ScanRequest(frame(height=1.0), 0.01, 0.1, 2.0), machine)
    # One row: 10.2 mm at 2 mm/s, the first-move delay, and the fixed
    # cost per row (measured on the bench).
    from multilbic.scan.raster import ROW_OVERHEAD_S

    assert one.estimate_s == pytest.approx(
        5.1 + 0.04 + 0.1 + ROW_OVERHEAD_S, abs=0.02)
    assert ten.estimate_s > 10 * one.estimate_s
