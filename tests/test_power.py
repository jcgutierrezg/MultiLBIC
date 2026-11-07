"""Each laser's power on the photodiode before and after its map (D31):
warmed up there, read again after the last row, the drift between."""

from dataclasses import replace

import pytest

from multilbic.bench.report import provenance
from multilbic.clock import ScaledClock
from multilbic.run.locate import POWER_S, Locator
from multilbic.run.rows import ScanDevices
from multilbic.run.session import RunRequest, Session, estimate_run
from multilbic.scan.mapping import BASELINE_ROW, WARMUP_ROW, build_map
from multilbic.sim.rig import Faults, SimRig
from multilbic.sim.sample import SyntheticSample
from multilbic.sim.scan import sim_machine
from multilbic.store.runfile import read_run

CORNER = (15.0, 16.0)
#: 1 % more light every simulated second.
DRIFT_PER_MIN = 0.6

# Located runs of the simulated machine: skipped on the Pi as the other
# simulator-timing tests are.
pytestmark = pytest.mark.sim_timing


def located_run(tmp_path, machine, *, lasers=(3,), warmup_s=3.0, **faults):
    f = replace(Faults(), **faults)
    machine = sim_machine(machine, f)
    rig = SimRig(machine, ScaledClock(20.0, precise=True),
                 SyntheticSample.default(1.0, 0.3), CORNER, f,
                 smu_channels=(1, 2))
    request = RunRequest(
        rig.perfect_calibration("synthetic"), lasers, 0.01, 0.05, 2.0,
        baseline_s=0.5, warmup_s=warmup_s, locate=True)
    rig.open()
    try:
        session = Session(ScanDevices(rig.marlin, rig.laser, rig.smu),
                          machine, rig.clock, request, tmp_path,
                          simulated=True, provenance=provenance())
        outcome = session.run()
    finally:
        rig.close()
    return outcome, rig, session


def test_the_power_is_read_before_and_after_each_map(tmp_path, machine):
    outcome, rig, _ = located_run(tmp_path, machine,
                                  laser_drift_per_min=DRIFT_PER_MIN)
    assert outcome.status == "complete", outcome.status
    run = read_run(outcome.lasers[0].path)
    h = run.header
    assert h["warmup_on"] == "photodiode"
    before, after, dark = h["power_before"], h["power_after"], \
        h["power_dark"]
    # The warm-up's curve, a reading a second, then the power.
    assert len(before["warmup"]) == 3
    assert [t for t, _ in before["warmup"]] == pytest.approx(
        [0.0, 1.0, 2.0], abs=0.15)
    assert before["readings"] >= 3 and after["readings"] >= 3
    assert before["range_a"] == h["located"]["range_a"]
    # Negative, as the cell reads; the dark next to nothing.
    assert before["current_a"] < 0 and after["current_a"] < 0
    assert abs(dark["current_a"]) < 1e-3 * abs(after["current_a"])
    # Every row between the two readings, and the drift between them as
    # the simulated laser drifted.
    assert all(before["t_s"] < a.sent_s and a.end_s < after["t_s"]
               for a in run.anchors)
    expected = rig.power_factor(after["t_s"]) / rig.power_factor(
        before["t_s"])
    assert after["current_a"] / before["current_a"] == pytest.approx(
        expected, rel=0.01)
    assert expected > 1.05
    # The baseline is in the file; the warm-up's samples aren't (the
    # photodiode was read, not streamed); the map builds as before.
    assert (run.columns["row"] == BASELINE_ROW).any()
    assert not (run.columns["row"] == WARMUP_ROW).any()
    assert build_map(run.scan_data()).alignment.found


def test_a_failed_power_reading_leaves_the_map(tmp_path, machine,
                                               monkeypatch):
    def broken(self, fix, read_s=5.0):
        raise RuntimeError("photodiode unplugged (planted)")

    monkeypatch.setattr(Locator, "power_after", broken)
    outcome, _, _ = located_run(tmp_path, machine, warmup_s=0.0)
    assert outcome.status == "complete", outcome.status
    h = read_run(outcome.lasers[0].path).header
    assert "unplugged" in h["power_after_error"]
    assert "power_after" not in h
    assert "power_before" in h


def test_the_estimate_counts_the_power_readings(machine):
    f = Faults()
    machine = sim_machine(machine, f)
    rig = SimRig(machine, ScaledClock(20.0), SyntheticSample.default(0.4, 0.15),
                 CORNER, f, smu_channels=(1, 2))
    request = RunRequest(rig.perfect_calibration("synthetic"), (1, 3), 0.01,
                         0.05, 2.0, locate=True)
    from multilbic.run.session import plan_run

    plans = plan_run(request, machine)
    located = estimate_run(plans, request, machine)
    plain = estimate_run(plans, replace(request, locate=False), machine)
    assert all(e.power_s == POWER_S for e in located.lasers)
    assert all(e.power_s == 0.0 for e in plain.lasers)
