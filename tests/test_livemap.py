"""The live map and the run's progress, without a window."""

import numpy as np
import pytest

from multilbic.clock import ScaledClock
from multilbic.gui.livemap import LiveMap, RunProgress, shrink
from multilbic.run.rows import RowDone, ScanDevices
from multilbic.run.session import RunRequest, Session, plan_run
from multilbic.scan.mapping import BASELINE_ROW, WARMUP_ROW, build_map
from multilbic.sim.rig import Faults, SimRig
from multilbic.sim.sample import SyntheticSample
from multilbic.sim.scan import sim_machine
from multilbic.store.runfile import SampleRow, read_run


def plan_for(machine, size=(1.0, 0.2), pixel=0.05, pitch=0.05, laser=2):
    rig = SimRig(machine, ScaledClock(20.0), SyntheticSample.default(*size),
                 (15.0, 16.0), Faults())
    request = RunRequest(rig.perfect_calibration("x"), (laser,), pixel, pitch,
                         1.0, baseline_s=0.5, warmup_s=0.0)
    return plan_run(request, machine)[0]


def block(row, a_values, currents, laser=2, rows=4, t0=0.0):
    samples = tuple(
        # One sample a millisecond, on the SMU's clock and the host's.
        SampleRow(row, 1, 1, i * 1.0, t0 + i * 1e-3, c, 0.0, a, 0.0)
        for i, (a, c) in enumerate(zip(a_values, currents, strict=True))
    )
    return RowDone(laser, row, rows, samples)


def test_rows_are_binned_with_the_baseline_taken_off(machine):
    plan = plan_for(machine)
    live = LiveMap(plan, mains_hz=50.0)
    assert live.values().shape == (4, 20)
    assert np.isnan(live.values()).all()
    origin = plan.placement.frame.origin_ab_mm[0]
    live.add(block(BASELINE_ROW, [0.0] * 50, [2e-9] * 50))
    live.add(block(WARMUP_ROW, [0.0] * 50, [9e-9] * 50))
    assert live.offset_a == pytest.approx(2e-9)
    # Row 1: 5 nA on the first half of the sample, 1 nA on the rest,
    # sampled every 5 um, plus the run-up outside the sample.
    a = origin + np.arange(-0.2, 1.2, 0.005)
    u = a - origin
    current = np.where(u < 0.5, 5e-9, 1e-9) + 2e-9
    live.add(block(1, a, current))
    values = live.values()
    assert live.rows_done == 1
    assert np.isnan(values[0]).all() and np.isfinite(values[1]).all()
    assert values[1, :9] == pytest.approx(5e-9, abs=0.05e-9)
    assert values[1, 11:] == pytest.approx(1e-9, abs=0.05e-9)


def test_a_big_live_map_bins_into_blocks(machine):
    plan = plan_for(machine, size=(10.0, 0.2), pixel=0.005)  # 2000 columns
    live = LiveMap(plan, mains_hz=50.0, limit=500)
    assert live.col_block == 4 and live.values().shape == (4, 500)
    origin = plan.placement.frame.origin_ab_mm[0]
    a = origin + np.arange(0.0, 10.0, 0.001)
    live.add(block(2, a, np.full(a.size, 3e-9)))
    row = live.values()[2]
    assert np.isfinite(row).all() and row == pytest.approx(3e-9, rel=1e-3)


def test_big_maps_are_averaged_down_for_the_screen():
    values = np.arange(12.0).reshape(3, 4)
    values[0, 0] = np.nan
    small = shrink(values, limit=2)
    assert small.shape == (2, 2)
    # The top-left block averages the finite three of its four.
    assert small[0, 0] == pytest.approx(np.mean([1.0, 4.0, 5.0]))
    assert shrink(values, limit=10) is values


def test_progress_uses_the_estimate_then_the_pace(machine):
    plans = (plan_for(machine), plan_for(machine, laser=1))
    progress = RunProgress(plans, estimate_s=100.0, started_s=0.0,
                           overhead_per_laser_s=10.0)
    assert progress.rows_total == 8
    assert progress.remaining_s(30.0) == pytest.approx(70.0)
    progress.block(RowDone(2, BASELINE_ROW, 4, ()), 5.0)
    for k, t in enumerate((7.0, 9.0, 11.0, 13.0)):
        progress.block(RowDone(2, k, 4, ()), t)
    # Four rows of eight done at 2 s a row, and the second laser's
    # baseline, warm-up and switch still to come.
    assert progress.rows_done == 4
    assert progress.remaining_s(13.0) == pytest.approx(4 * 2.0 + 10.0)
    assert 0 < progress.fraction(13.0) < 1


@pytest.mark.sim_timing  # see tests/test_sim_scan.py
def test_the_live_map_agrees_with_the_finished_one(machine, tmp_path):
    faults = Faults()
    machine = sim_machine(machine, faults)
    clock = ScaledClock(5.0, precise=True)
    rig = SimRig(machine, clock, SyntheticSample.default(1.0, 0.4),
                 (15.0, 16.0), faults)
    rig.open()
    request = RunRequest(rig.perfect_calibration("x"), (2,), 0.01, 0.05,
                         2.0, baseline_s=0.5, warmup_s=0.0)
    live = LiveMap(plan_run(request, machine)[0], machine.mains_hz)
    try:
        outcome = Session(
            ScanDevices(rig.marlin, rig.laser, rig.smu), machine, clock,
            request, tmp_path, simulated=True, provenance={},
            on_row=live.add,
        ).run()
    finally:
        rig.close()
    assert outcome.status == "complete"
    final = build_map(read_run(outcome.lasers[0].path).scan_data())
    a, b = live.values(), final.grid.values
    assert a.shape == b.shape
    both = np.isfinite(a) & np.isfinite(b)
    assert both.mean() > 0.9
    # Alike but for the serpentine shift the finished map removes, which
    # on 10 um pixels moves the fingers' edges by a pixel or two.
    assert np.corrcoef(a[both], b[both])[0, 1] > 0.8
    assert np.nanmedian(np.abs(a - b)) < 0.1 * np.nanmax(np.abs(b))
