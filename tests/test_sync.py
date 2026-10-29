"""Step-and-measure and the sync check (Phase 6, step 2): the plans,
the analysis, and a whole check against the simulated machine."""

import json
import math
from dataclasses import replace

import numpy as np
import pytest

from multilbic import cli
from multilbic.clock import ScaledClock
from multilbic.run.rows import ScanDevices
from multilbic.run.session import RunPlanError
from multilbic.run.steps import MAX_POINTS, StepRequest, plan_steps
from multilbic.run.sync import SyncCheck, SyncRequest, analyse, plan_sync
from multilbic.scan.edges import EdgeFit, RowEdge
from multilbic.scan.geometry import SampleFrame
from multilbic.scan.raster import RasterError
from multilbic.scan.sync import (
    Offset,
    PassResult,
    Reference,
    ScanEdges,
    drift,
    fit_speeds,
    point_rows,
)
from multilbic.sim.fake_smu import FakeMiniSMU
from multilbic.sim.rig import Faults, SimRig
from multilbic.sim.sample import SyntheticSample
from multilbic.sim.scan import sim_machine
from multilbic.store.runfile import RunWriter, SampleRow, read_run

CORNER = (15.0, 16.0)


# ---- plans ----


def test_step_plan_points_rows_and_whole_mains_periods(machine):
    frame = SampleFrame((17.0, 17.0), 0.2, 0.3)
    plan = plan_steps(StepRequest(frame, 0.01, 0.1, settle_s=0.1,
                                  dwell_s=0.05), machine)
    assert len(plan.rows) == 3
    assert [r.b_mm for r in plan.rows] == pytest.approx([17.05, 17.15, 17.25])
    assert len(plan.rows[0].a_mm) == 21
    assert plan.rows[0].a_mm[0] == pytest.approx(17.0)
    assert plan.rows[0].a_mm[-1] == pytest.approx(17.2)
    assert plan.dwell_s == pytest.approx(0.06)  # three 50 Hz periods
    assert plan.estimate_s > plan.points * (0.1 + 0.06)


def test_step_plan_refuses_too_many_points_and_the_unsafe(machine):
    big = SampleFrame((5.0, 5.0), 10.0, 10.0)
    with pytest.raises(RasterError, match="more than"):
        plan_steps(StepRequest(big, 0.01, 0.01), machine)
    assert MAX_POINTS < 1001 * 1000
    edge = SampleFrame((39.4, 17.0), 0.2, 0.2)
    with pytest.raises(RasterError, match="safe range"):
        plan_steps(StepRequest(edge, 0.01, 0.1), machine)


def _rig(machine, faults=None, size=(1.0, 0.4), edge_u=0.5):
    faults = faults or Faults()
    machine = sim_machine(machine, faults)
    clock = ScaledClock(3.0, precise=True)
    rig = SimRig(machine, clock,
                 SyntheticSample.straight_edge(*size, edge_u), CORNER, faults)
    return rig, machine, clock


def test_sync_plan_passes_share_the_patch_and_its_rows(machine):
    rig, machine, _ = _rig(machine)
    request = SyncRequest(rig.perfect_calibration("edge"), 2,
                          window_mm=(0.4, 0.6, 0.1, 0.3), pitch_mm=0.05,
                          speeds_mm_s=(1.0, 4.0))
    plan = plan_sync(request, machine)
    assert [p.name for p in plan.passes] == [
        "p1_steps", "p2_1mm_s", "p3_4mm_s", "p4_steps"]
    steps = plan.passes[0].steps
    raster = plan.passes[1].raster
    assert steps is not None and raster is not None
    assert [r.b_mm for r in steps.rows] == pytest.approx(
        [r.b_mm for r in raster.rows])
    assert plan.frame.width_mm == pytest.approx(0.2)
    no_repeat = plan_sync(replace(request, repeat_steps=False), machine)
    assert len(no_repeat.passes) == 3


@pytest.mark.parametrize("change, message", [
    ({"window_mm": (0.5, 1.5, 0.0, 0.2)}, "inside the sample"),
    ({"laser": 4}, "placeholder"),
    ({"laser": 9}, "no laser 9"),
    ({"speeds_mm_s": (1.0, 0.0)}, "> 0"),
])
def test_sync_plan_refuses_before_anything_moves(machine, change, message):
    rig, machine, _ = _rig(machine)
    request = replace(SyncRequest(rig.perfect_calibration("edge"), 2),
                      **change)
    with pytest.raises(RunPlanError, match=message):
        plan_sync(request, machine)


# ---- analysis ----


def _fit(position):
    return EdgeFit(position, 0.016, 0.0, -1e-6, 0.0, 1e-4, 1e-4, 1e-9, 100)


def _pass(speed, forward, reverse):
    return PassResult(f"{speed}", speed, Offset(forward, 0.0, 5),
                      Offset(reverse, 0.0, 5), ScanEdges([], {}, None, None))


def test_fit_speeds_separates_timing_from_backlash():
    lag, backlash = 0.0186, 0.020
    results = [_pass(v, lag * v, -backlash - lag * v) for v in (1, 4, 5)]
    fit = fit_speeds(results)
    assert fit is not None
    assert fit.lag_ms == pytest.approx(18.6)
    assert fit.backlash_mm == pytest.approx(0.020)
    assert fit.forward_mm == pytest.approx(0.0, abs=1e-12)
    assert fit.residual_mm == pytest.approx(0.0, abs=1e-12)
    # One pass alone can't tell them apart.
    assert fit_speeds(results[:1]) is None
    assert results[0].lag_ms == pytest.approx((0.0186 * 2 + 0.02) / 2 * 1000)


def test_reference_averages_passes_and_interpolates_in_b():
    first = [RowEdge(k, 0, 10.0 + 0.1 * k, _fit(1.0 + 0.01 * k))
             for k in range(3)]
    second = [RowEdge(k, 0, 10.0 + 0.1 * k, _fit(1.002 + 0.01 * k))
              for k in range(3)]
    ref = Reference([first, second], 0.1)
    assert ref.at(10.05) == pytest.approx(1.006)
    assert ref.covers(9.96) and ref.covers(10.24)
    assert not ref.covers(9.9) and not ref.covers(10.31)
    moved = drift(first, second)
    assert moved is not None
    assert moved.median_mm == pytest.approx(0.002)
    assert moved.count == 3


def test_point_rows_average_each_point_less_the_baseline(tmp_path):
    path = tmp_path / "steps.csv"
    writer = RunWriter(path, {"mode": "steps"})

    def sample(row, a, amps):
        return SampleRow(row, 0, 1, 0.0, 0.0, amps, 0.0, a, 17.05)

    writer.write_samples([sample(-1, 0.0, 1e-9), sample(-1, 0.0, 3e-9)])
    writer.write_samples([sample(0, 17.0, 5e-9), sample(0, 17.0, 7e-9),
                          sample(0, 17.01, 2e-9), sample(0, 17.01, 2e-9)])
    writer.finish("complete", {})
    (row,) = point_rows(read_run(path))
    assert row.b_mm == pytest.approx(17.05)
    assert row.a_mm == pytest.approx([17.0, 17.01])
    assert row.mean_a == pytest.approx([4e-9, 0.0])
    assert list(row.count) == [2, 2]
    assert row.sem_a[1] == pytest.approx(0.0)


# ---- the simulator's additions ----


def test_the_fake_smu_stamps_late_by_its_stamp_lag():
    clock = ScaledClock(20.0)
    lag = 0.0186
    # The current is the time it was measured at, so each packet says
    # when it was measured and its stamp says when it was stamped.
    smu = FakeMiniSMU(clock, signal=lambda channel, t: t, stamp_lag_s=lag)
    smu.enable_channel(1)
    smu.set_sample_rate(1, 200)
    smu.start_streaming(1)
    clock.sleep(0.3)
    lines = smu._connection.read(100_000).decode().split()
    gaps = []
    for line in lines[:50]:
        _, stamp, _, amps, _ = line.split(",")
        gaps.append(smu.true_time(float(stamp)) - float(amps))
    assert np.median(gaps) == pytest.approx(lag, abs=0.001)


def test_the_straight_edge_sample_is_half_lit_on_its_edge():
    sample = SyntheticSample.straight_edge(2.0, 2.0, 1.0, cell_a=1e-6)
    # Its spectrum is flat over the lasers' range, to 1e-7.
    assert sample.current(519, 1.0, 1.0) == pytest.approx(0.5e-6, rel=1e-4)
    assert sample.current(848, 0.9, 1.0) == pytest.approx(1e-6, rel=1e-4)
    assert sample.current(519, 1.1, 1.0) == pytest.approx(0.0, abs=1e-12)


# ---- a whole check ----


@pytest.mark.sim_timing  # see tests/test_sim_scan.py
def test_sync_check_recovers_the_stamp_lag_and_backlash(machine, tmp_path,
                                                        capsys):
    """The bench's 18.6 ms stamp lag and 20 um of A backlash, injected
    with nothing else: the check has to find both, and the spot."""
    faults = replace(Faults.none(), backlash_mm=0.020, xy_backlash_mm=0.1,
                     smu_stamp_lag_s=0.0186)
    rig, machine, clock = _rig(machine, faults)
    rig.open()
    request = SyncRequest(
        rig.perfect_calibration("edge"), 2, window_mm=(0.4, 0.6, 0.1, 0.3),
        step_mm=0.01, pitch_mm=0.05, speeds_mm_s=(1.0, 4.0), settle_s=0.02,
        dwell_s=0.04, baseline_s=0.3, warmup_s=0.0, pass_warmup_s=0.0)
    try:
        check = SyncCheck(ScanDevices(rig.marlin, rig.laser, rig.smu),
                          machine, clock, request, tmp_path, simulated=True,
                          provenance={"commit": "test"})
        outcome = check.run()
    finally:
        rig.close()
    assert outcome.status == "complete", outcome.status
    result = outcome.result
    assert result is not None
    fit = result["fit"]
    assert fit["lag_ms"] == pytest.approx(18.6, abs=1.5)
    assert fit["backlash_um"] == pytest.approx(20.0, abs=3.0)
    assert abs(result["drift"]["drift_um"]) < 1.0
    true_width_um = 2.5631 * rig.sample.spot_sigma_mm * 1000
    for steps in result["steps"]:
        assert steps["rows_fitted"] == 4
        assert steps["median_width_um"] == pytest.approx(true_width_um,
                                                         rel=0.1)
    # The serpentine shift is the sum, backlash + 2 L v: the edges'
    # shift agrees with the fit's parts.
    for p in result["passes"]:
        expected = fit["backlash_um"] + 2 * fit["lag_ms"] * p["speed_mm_s"]
        assert p["edge_shift"]["shift_um"] == pytest.approx(expected, abs=3)

    # Everything is on disk, and the result can be worked out again.
    summary = json.loads((outcome.folder / "sync.json").read_text())
    assert summary["status"] == "complete"
    assert [p["status"] for p in summary["passes"]] == ["complete"] * 4
    assert (outcome.folder / "p2_1mm_s.png").exists()
    again = analyse(outcome.folder)
    assert again["fit"]["lag_ms"] == pytest.approx(fit["lag_ms"])

    # And from the command line.
    capsys.readouterr()
    assert cli.main(["edges", str(outcome.folder)]) == 0
    assert "timing error L =" in capsys.readouterr().out
    assert cli.main(["edges", str(outcome.folder / "p3_4mm_s.csv")]) == 0
    assert "shift from edges" in capsys.readouterr().out


@pytest.mark.sim_timing
def test_stop_during_step_and_measure_keeps_the_rows(machine, tmp_path):
    rig, machine, clock = _rig(machine, replace(Faults.none(),
                                                xy_backlash_mm=0.1))
    rig.open()
    request = SyncRequest(
        rig.perfect_calibration("edge"), 2, window_mm=(0.4, 0.6, 0.1, 0.3),
        pitch_mm=0.05, speeds_mm_s=(1.0,), settle_s=0.02, dwell_s=0.04,
        baseline_s=0.3, warmup_s=0.0, pass_warmup_s=0.0)
    said = []
    try:
        check = SyncCheck(ScanDevices(rig.marlin, rig.laser, rig.smu),
                          machine, clock, request, tmp_path, simulated=True,
                          provenance={}, say=said.append)

        def stop_after_row_two(text):
            said.append(text)
            if text.startswith("row 2/"):
                check.request_stop()

        check.say = stop_after_row_two
        outcome = check.run()
    finally:
        rig.close()
    assert outcome.status == "stopped"
    assert rig.fake_laser.active == 0
    run = read_run(outcome.folder / "p1_steps.csv")
    assert run.header["status"] == "stopped"
    assert [r.row for r in point_rows(run)] == [0, 1]
    assert not (outcome.folder / "p2_1mm_s.csv").exists()
    assert not math.isnan(point_rows(run)[0].mean_a[0])
