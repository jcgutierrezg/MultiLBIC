"""EQE from a map and the photodiode's readings (D31, D32): the
datasheet's curve, which response a map rests on, the power over the
map, and a simulated run whose laser drifts while its EQE doesn't."""

import math
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from multilbic.scan import eqe

# ---- the arithmetic ----


def test_the_datasheet_curve():
    # The datasheet's table, exactly.
    assert eqe.datasheet_response(660) == pytest.approx(0.45)
    assert eqe.datasheet_response(780) == pytest.approx(0.52)
    assert eqe.datasheet_response(830) == pytest.approx(0.54)
    assert eqe.datasheet_response(960) == pytest.approx(0.60)
    # Between points, a straight line: laser 1's 444 nm.
    assert eqe.datasheet_response(444) == pytest.approx(
        0.17 + (0.235 - 0.17) * 44 / 50)
    assert math.isnan(eqe.datasheet_response(1064))
    # Rising with wavelength up to the peak.
    values = [r for _, r, _ in eqe.S1223_01_A_W]
    assert values == sorted(values)


def test_the_response_measured_with_the_run_wins():
    run = {"pd_response_a_w": 0.43, "pd_response_date": "2026-11-10"}
    r = eqe.response_for(run, 652, (0.47, "2026-12-01"))
    assert (r.a_w, r.source, r.taken_from) == (0.43, "measured", "run")
    assert "measured 2026-11-10" in r.describe()
    # Measured only since: machine.toml's now, said so.
    r = eqe.response_for({"pd_response_a_w": None}, 652, (0.47, "2026-12-01"))
    assert (r.a_w, r.taken_from) == (0.47, "now")
    assert "after the run" in r.describe()
    # Never measured: the datasheet, said so.
    r = eqe.response_for({}, 652)
    assert r.source == "datasheet" and "datasheet" in r.describe()
    assert r.a_w == pytest.approx(eqe.datasheet_response(652))
    assert eqe.response_for({}, 1064) is None


def header(before=-2.0e-3, after=-2.2e-3, dark=-1e-6):
    return {"power_before": {"current_a": before, "t_s": 100.0},
            "power_after": {"current_a": after, "t_s": 200.0},
            "power_dark": {"current_a": dark, "t_s": 205.0}}


def test_the_power_between_the_readings():
    track = eqe.PowerTrack.from_header(header())
    # The dark taken out of both.
    assert track.before_a == pytest.approx(-2.0e-3 + 1e-6)
    assert track.drift == pytest.approx((-2.2e-3 + 1e-6) / (-2.0e-3 + 1e-6)
                                        - 1)
    mid = track.at(np.array([150.0]))[0]
    assert mid == pytest.approx((track.before_a + track.after_a) / 2)
    # Held level beyond the readings.
    assert track.at(np.array([50.0, 300.0])).tolist() == pytest.approx(
        [track.before_a, track.after_a])
    assert "+10.0%" in track.describe()
    # Before only: level all through.
    only = eqe.PowerTrack.from_header({"power_before": {"current_a": -1e-3,
                                                        "t_s": 1.0}})
    assert only.drift is None
    assert only.at(np.array([0.0, 9.0])).tolist() == [-1e-3, -1e-3]
    assert eqe.PowerTrack.from_header({}) is None


def test_eqe_worked_by_hand():
    # 1 mA from the cell, 2 mA from the photodiode at 0.5 A/W, 620 nm:
    # the beam is 4 mW, 1 mA is 0.5 * 1239.84 / 620 = 0.99997 of the
    # photons: EQE = 0.5 * 0.99997.
    track = eqe.PowerTrack(0.0, -2e-3)
    r = eqe.Response(0.5, "measured")
    values = np.array([[-1e-3, np.nan]])
    out = eqe.eqe_map(values, np.array([5.0]), track, r, 620.0)
    assert out[0, 0] == pytest.approx(0.5 * 1239.84193 / 620 * 0.5)
    assert math.isnan(out[0, 1])
    # A row with no time has no EQE.
    assert math.isnan(eqe.eqe_map(values, np.array([np.nan]),
                                  eqe.PowerTrack(0.0, -2e-3, 10.0, -2e-3),
                                  r, 620.0)[0, 0])


def test_row_times_are_the_middle_of_each_move():
    anchors = [SimpleNamespace(index=0, sent_s=10.0, end_s=11.0),
               SimpleNamespace(index=2, sent_s=14.0, end_s=16.0)]
    times = eqe.row_times(anchors, 3)
    assert times[0] == 10.5 and math.isnan(times[1]) and times[2] == 15.0


# ---- a simulated run whose laser drifts ----


@pytest.mark.sim_timing
def test_a_drifting_laser_gives_a_steady_eqe(tmp_path, machine):
    from multilbic.bench.report import provenance
    from multilbic.clock import ScaledClock
    from multilbic.run.rows import ScanDevices
    from multilbic.run.session import RunRequest, Session
    from multilbic.sim.rig import Faults, SimRig
    from multilbic.sim.sample import SyntheticSample
    from multilbic.sim.scan import sim_machine
    from multilbic.store.runfolder import read_folder

    f = replace(Faults(), laser_drift_per_min=4.8)  # 8 % a second
    machine = sim_machine(machine, f)
    rig = SimRig(machine, ScaledClock(20.0, precise=True),
                 SyntheticSample.default(1.0, 0.6, cell_a=20e-6),
                 (15.0, 16.0), f, smu_channels=(1, 2))
    request = RunRequest(rig.perfect_calibration("synthetic"), (3,), 0.01,
                         0.05, 2.0, baseline_s=0.5, warmup_s=0.0,
                         locate=True)
    rig.open()
    try:
        outcome = Session(ScanDevices(rig.marlin, rig.laser, rig.smu),
                          machine, rig.clock, request, tmp_path,
                          simulated=True, provenance=provenance()).run()
    finally:
        rig.close()
    assert outcome.status == "complete", outcome.status
    run = read_folder(outcome.folder, machine=machine)
    m = run.maps[3]
    assert m.eqe is not None and m.no_eqe is None
    assert m.response.source == "datasheet"
    assert m.power.drift > 0.1

    def level(values, rows):
        """The cell's bright level over these rows: the median of each
        row's brightest tenth."""
        per_row = []
        for k in rows:
            row = np.abs(values[k][np.isfinite(values[k])])
            per_row.append(np.median(np.sort(row)[-max(3, row.size // 10):]))
        return float(np.median(per_row))

    # The rows that cross the cell (the synthetic cells don't reach the
    # frame's edges): the first three and the last three of them.
    levels = [level(m.values, [k]) for k in range(m.values.shape[0])]
    crossing = [k for k, lv in enumerate(levels) if lv > 0.5 * max(levels)]
    assert len(crossing) >= 8
    first, last = crossing[:3], crossing[-3:]
    raw_growth = level(m.values, last) / level(m.values, first) - 1
    eqe_growth = level(m.eqe, last) / level(m.eqe, first) - 1
    # The current follows the laser; the EQE doesn't.
    assert raw_growth > 0.04  # +6 % on the PC, 2026-11-07
    assert abs(eqe_growth) < raw_growth / 4
