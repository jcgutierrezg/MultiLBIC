"""Placing each map from the photodiode: locating a laser where the servo
landed it, and runs whose maps line up although the servo scatters."""

from dataclasses import replace

import numpy as np
import pytest

from multilbic.bench.report import provenance
from multilbic.clock import ScaledClock
from multilbic.run.locate import Locator
from multilbic.run.rows import ScanDevices
from multilbic.run.session import RunPlanError, RunRequest, Session
from multilbic.scan.mapping import build_map
from multilbic.sim.rig import Faults, SimRig
from multilbic.sim.sample import SyntheticSample
from multilbic.sim.scan import SimScan, position_errors, sim_machine
from multilbic.store.runfile import read_run

CORNER = (15.0, 16.0)

# Runs of the simulated machine measured to a few um: skipped on the Pi
# as the other simulator-timing tests are.
pytestmark = pytest.mark.sim_timing


def rig_for(machine, **faults):
    f = replace(Faults(), **faults)
    machine = sim_machine(machine, f)
    rig = SimRig(machine, ScaledClock(20.0, precise=True),
                 SyntheticSample.default(1.0, 0.3), CORNER, f,
                 smu_channels=(1, 2))
    return rig, machine


def test_a_laser_off_its_position_is_found_where_it_is(machine):
    rig, machine = rig_for(machine)
    x, y = rig.laser_xy_mm[3]
    rig.laser_xy_mm[3] = (x + 0.12, y - 0.07)
    rig.open()
    try:
        devices = ScanDevices(rig.marlin, rig.laser, rig.smu)
        rig.marlin.home()
        fix = Locator(devices, machine, rig.clock,
                      say=lambda _: None).locate(3)
    finally:
        rig.close()
    assert fix.quick
    # Against where it really is, as commissioning measures it (XY
    # placing moves leave half the XY backlash, the same for every laser).
    half = rig.faults.xy_backlash_mm / 2
    assert fix.offset_xy_mm == pytest.approx((0.12 + half, -0.07 + half),
                                             abs=0.004)
    # Left lit: the map that follows uses this landing.
    assert rig.fake_laser.active == 3


def test_further_off_than_the_servo_the_full_sweeps_find_it(machine):
    rig, machine = rig_for(machine)
    x, y = rig.laser_xy_mm[3]
    rig.laser_xy_mm[3] = (x + 0.7, y)
    rig.open()
    try:
        rig.marlin.home()
        fix = Locator(ScanDevices(rig.marlin, rig.laser, rig.smu), machine,
                      rig.clock, say=lambda _: None).locate(3)
    finally:
        rig.close()
    assert not fix.quick
    half = rig.faults.xy_backlash_mm / 2
    assert fix.offset_xy_mm[0] == pytest.approx(0.7 + half, abs=0.005)


def run_three(tmp_path, machine, *, locate, scatter):
    rig, machine = rig_for(machine, servo_scatter_mm=scatter)
    request = RunRequest(
        rig.perfect_calibration("synthetic"), (1, 2, 3), 0.005, 0.05, 2.0,
        baseline_s=0.5, warmup_s=0.0, locate=locate)
    rig.open()
    try:
        session = Session(ScanDevices(rig.marlin, rig.laser, rig.smu),
                          machine, rig.clock, request, tmp_path,
                          simulated=True, provenance=provenance())
        outcome = session.run()
    finally:
        rig.close()
    assert outcome.status == "complete", outcome.status
    # Each sample's mapped A against where the spot really was (the
    # simulator knows): the median per laser, mapped minus true, before
    # the serpentine alignment (which adds noise of its own on this
    # sample, and doesn't place anything).
    errors = {}
    for o in outcome.lasers:
        result = build_map(read_run(o.path).scan_data())
        found = position_errors(SimScan(o.path, result, rig.sample, rig,
                                        o.laser)).before
        assert found.size, o.laser
        errors[o.laser] = float(np.median(found))
    return outcome, errors


def test_with_the_servo_scattering_located_maps_line_up(tmp_path, machine):
    _, off = run_three(tmp_path / "off", machine, locate=False,
                       scatter=0.15)
    outcome, on = run_three(tmp_path / "on", machine, locate=True,
                            scatter=0.15)
    spread_off = max(off.values()) - min(off.values())
    spread_on = max(on.values()) - min(on.values())
    # The servo's tens of um, against the photodiode's few. (Located,
    # every map also sits 50 um off: here machine.toml's corner is the
    # true one, while a measured corner carries half the XY backlash, as
    # on the bench it is measured with.)
    # The seeded servo lands them 34-139 um off along X; this measure
    # itself scatters about 10 um a laser from run to run.
    assert spread_off > 0.06
    assert spread_on < 0.025
    assert spread_on < spread_off / 4
    # Recorded: the run file and run.json say where each was located.
    for o in outcome.lasers:
        assert o.fix is not None
        header = read_run(o.path).header
        assert header["located"]["laser"] == o.laser


def test_locating_needs_the_photodiode_channel(machine):
    rig, machine = rig_for(machine)
    rig.smu_channels = (1,)
    request = RunRequest(rig.perfect_calibration("synthetic"), (2,), 0.005,
                         0.05, 2.0, locate=True)
    rig2 = SimRig(machine, ScaledClock(20.0), SyntheticSample.default(),
                  CORNER, Faults(), smu_channels=(1,))
    rig2.open()
    try:
        with pytest.raises(RunPlanError, match="channel 2"):
            Session(ScanDevices(rig2.marlin, rig2.laser, rig2.smu), machine,
                    rig2.clock, request, "unused", simulated=True,
                    provenance={})
    finally:
        rig2.close()
