"""A whole run: several lasers, Stop, faults, and what's refused before
anything moves. Everything here runs against the simulated machine."""

import json
import threading
import time
from dataclasses import replace

import numpy as np
import pytest

from multilbic.clock import ScaledClock
from multilbic.run.rows import ScanDevices
from multilbic.run.session import RunPlanError, RunRequest, Session, plan_run
from multilbic.scan.mapping import build_map
from multilbic.sim.rig import Faults, SimRig
from multilbic.sim.sample import SyntheticSample
from multilbic.sim.scan import _crossing, sim_machine
from multilbic.store.runfile import read_run

CORNER = (15.0, 16.0)


def make(machine, clock, *, size=(0.6, 0.2), faults=None, cell_a=1e-6,
         **truth):
    faults = faults or Faults()
    machine = sim_machine(machine, faults)
    rig = SimRig(machine, clock,
                 SyntheticSample.default(*size, cell_a=cell_a), CORNER,
                 faults, **truth)
    rig.open()
    return rig, machine


def request(rig, lasers=(2,), **options):
    settings = dict(pixel_mm=0.005, pitch_mm=0.05, speed_mm_s=1.0,
                    baseline_s=0.5, warmup_s=0.0)
    settings.update(options)
    return RunRequest(rig.perfect_calibration("test cell"), lasers,
                      **settings)


def session(rig, machine, clock, req, tmp_path):
    return Session(ScanDevices(rig.marlin, rig.laser, rig.smu), machine,
                   clock, req, tmp_path, simulated=True,
                   provenance={"commit": "test"})


def finger_edges(path, sample, nm):
    """Where each row of the map puts the first finger's left edge."""
    grid = build_map(read_run(path).scan_data()).grid
    finger = sample.patches[2]
    edges = []
    for k, v in enumerate(grid.v_centres):
        if not finger.v0 + 0.02 < v < finger.v1 - 0.02:
            continue
        row = grid.values[k]
        u = grid.u_centres
        near = (u > finger.u0 - 0.012) & (u < finger.u0 + 0.008)
        inside = sample.current(nm, finger.u0 - 0.03, v)
        crossing = _crossing(u[near], row[near], inside / 2)
        if crossing is not None:
            edges.append(crossing)
    return np.array(edges), finger.u0


@pytest.mark.sim_timing  # see tests/test_sim_scan.py
def test_two_lasers_line_up_with_swapped_axes(machine, tmp_path):
    """The axes here are swapped and one is reversed, in machine.toml
    and in truth alike: the geometry has to get both lasers' XY right
    for their maps to land on the sample."""
    swapped = replace(machine, geometry=replace(
        machine.geometry, x_along="-B", y_along="+A"))
    clock = ScaledClock(3.0, precise=True)
    rig, swapped = make(swapped, clock)
    try:
        outcome = session(rig, swapped, clock,
                          request(rig, lasers=(1, 2)), tmp_path).run()
    finally:
        rig.close()
    assert outcome.status == "complete"
    for result in outcome.lasers:
        nm = swapped.laser(result.laser).wavelength_nm
        edges, true_edge = finger_edges(result.path, rig.sample, nm)
        assert edges.size >= 1, result.laser
        # This checks placement: a wrong axis would put the map
        # millimetres off, XY backlash not taken up 50 µm. The 5 µm sync
        # tolerance is Phase 3's test, on a taller sample; with two rows
        # here, one row's edge can stray a little further.
        errors = np.abs(edges - true_edge)
        assert np.median(errors) < 0.005, (result.laser, errors)
        assert errors.max() < 0.010, (result.laser, errors)
        assert result.png is not None and result.png.exists()
    summary = json.loads((outcome.folder / "run.json").read_text())
    assert summary["status"] == "complete"
    assert [p["laser"] for p in summary["plans"]] == [1, 2]
    xy = {p["laser"]: p["xy_mm"] for p in summary["plans"]}
    # Laser 1 sits 4 mm further along X than laser 2 (machine.toml), and
    # its placement moves XY by exactly that.
    assert xy[1][0] - xy[2][0] == pytest.approx(4.0)
    assert xy[1][1] - xy[2][1] == pytest.approx(-0.4)


def events(folder):
    lines = (folder / "events.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def test_stop_mid_run_leaves_everything_safe(machine, tmp_path):
    clock = ScaledClock(20.0)
    rig, machine = make(machine, clock, size=(1.0, 0.6))
    run = session(rig, machine, clock, request(rig, lasers=(2, 3)), tmp_path)
    done = {}
    worker = threading.Thread(target=lambda: done.update(o=run.run()))
    worker.start()
    try:
        # Wait for the second row to be on disk, then press Stop.
        path = run.folder / "laser2_519nm.csv"
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if path.exists() and path.read_text().count("#row:") >= 2:
                break
            time.sleep(0.02)
        run.request_stop()
        worker.join(30)
    finally:
        rig.close()
    outcome = done["o"]
    assert outcome.status == "stopped"
    assert [r.status for r in outcome.lasers] == ["stopped"]  # 3 never ran
    assert rig.fake_laser.active == 0
    assert not rig.fake_smu.enabled[1]
    assert not rig.fake_marlin.moving()
    data = read_run(path)
    assert data.header["status"] == "stopped"
    assert len(data.anchors) >= 2
    assert events(outcome.folder)[-1]["status"] == "stopped"


@pytest.mark.parametrize(
    ("fault", "kind"),
    [
        ("laser", "LaserBoardError"),
        ("smu", "StreamFault"),
        ("marlin", "MarlinTimeout"),
    ],
)
def test_a_fault_ends_the_run_safely(machine, tmp_path, fault, kind):
    clock = ScaledClock(20.0)
    rig, machine = make(machine, clock, size=(1.0, 0.4))
    run = session(rig, machine, clock, request(rig), tmp_path)

    def inject():
        # After the first row is on disk.
        path = run.folder / "laser2_519nm.csv"
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if path.exists() and "#row:" in path.read_text():
                break
            time.sleep(0.02)
        if fault == "laser":
            rig.fake_laser.silent = True
        elif fault == "smu":
            rig.fake_smu.stalled = True
        else:
            rig.fake_marlin.silent = True

    if fault == "laser":
        # The board only speaks when the laser is switched: break it
        # before it is lit.
        rig.fake_laser.silent = True
    else:
        threading.Thread(target=inject, daemon=True).start()
    try:
        outcome = run.run()
    finally:
        rig.close()
    assert outcome.status.startswith("failed"), outcome.status
    assert kind in outcome.status
    assert not rig.fake_smu.enabled[1]
    if fault != "laser":
        assert rig.fake_laser.active == 0
    status = read_run(outcome.lasers[0].path).header["status"]
    assert status.startswith("failed") and kind in status


def test_refused_before_anything_moves(machine):
    clock = ScaledClock(20.0)
    rig, machine = make(machine, clock)
    try:
        with pytest.raises(RunPlanError, match="placeholder"):
            plan_run(request(rig, lasers=(4,)), machine)
        assert plan_run(
            request(rig, lasers=(4,), allow_unmeasured=True), machine
        )
        with pytest.raises(RunPlanError, match="twice"):
            plan_run(request(rig, lasers=(2, 2)), machine)
        with pytest.raises(RunPlanError, match="no laser 9"):
            plan_run(request(rig, lasers=(9,)), machine)
        far = replace(rig.perfect_calibration(), corner_xy_mm=(150.0, 60.0))
        with pytest.raises(RunPlanError, match="outside"):
            plan_run(replace(request(rig), calibration=far), machine)
        assert not rig.fake_marlin.executed or all(
            not c.startswith("G1") for c in rig.fake_marlin.executed
        )
    finally:
        rig.close()


def test_a_saturated_range_stops_the_run(machine, tmp_path):
    """A cell twice as bright as usual gives about 1.7 uA under laser 2,
    well past the 1 uA range, so it clips whatever the noise does;
    clipped data is wrong, so the run stops and says why.

    Laser 2 because selecting it needs no servo turn. With the usual
    cell it gave 0.87 uA and only clipped when noise pushed it past
    0.98 uA (failed on the Pi, 0.4.8); laser 3 fixed that but its servo
    turn, at 20x, left the board's reply ~0.15 s real, which the Pi
    missed once (2026-10-26)."""
    clock = ScaledClock(20.0)
    rig, machine = make(machine, clock, cell_a=2e-6)
    try:
        req = replace(request(rig), current_range_a=1e-6)
        outcome = session(rig, machine, clock, req, tmp_path).run()
    finally:
        rig.close()
    assert outcome.status.startswith("failed")
    assert "larger --current-range" in outcome.status
    assert not rig.fake_smu.enabled[1]
    header = read_run(outcome.lasers[0].path).header
    assert header["current_range_a"] == 1e-6


def test_warmup_is_recorded_but_not_mapped(machine, tmp_path):
    clock = ScaledClock(20.0)
    rig, machine = make(machine, clock)
    try:
        req = replace(request(rig), warmup_s=2.0)
        outcome = session(rig, machine, clock, req, tmp_path).run()
    finally:
        rig.close()
    assert outcome.status == "complete"
    run = read_run(outcome.lasers[0].path)
    rows = run.columns["row"].astype(int)
    warm = rows == -2
    # About 2 s at 400 Hz, with the laser on: the cell's current, not dark.
    assert 600 < warm.sum() < 1000
    assert abs(run.columns["current_a"][warm]).mean() > 1e-8
    assert run.header["warmup_s"] == 2.0
    grid = build_map(run.scan_data()).grid
    assert grid.values.shape[0] == len(run.anchors)


def test_stop_during_warmup(machine, tmp_path):
    clock = ScaledClock(20.0)
    rig, machine = make(machine, clock)
    run = session(rig, machine, clock,
                  replace(request(rig), warmup_s=600.0), tmp_path)
    done = {}
    worker = threading.Thread(target=lambda: done.update(o=run.run()))
    worker.start()
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and rig.fake_laser.active == 0:
            time.sleep(0.02)
        assert rig.fake_laser.active == 2  # warming up
        started = time.monotonic()
        run.request_stop()
        worker.join(30)
        # 600 s simulated is 30 s real: it must not wait that out.
        assert time.monotonic() - started < 5
    finally:
        rig.close()
    assert done["o"].status == "stopped"
    assert rig.fake_laser.active == 0


def test_hooks_see_every_row_as_written_and_the_map(machine, tmp_path):
    from multilbic.scan.mapping import BASELINE_ROW, WARMUP_ROW

    clock = ScaledClock(20.0)
    rig, machine = make(machine, clock, size=(0.6, 0.2))
    rows, maps = [], []
    run = Session(ScanDevices(rig.marlin, rig.laser, rig.smu), machine,
                  clock, request(rig, warmup_s=0.5), tmp_path,
                  simulated=True, provenance={"commit": "test"},
                  on_row=rows.append,
                  on_map=lambda result, mapped: maps.append((result, mapped)))
    try:
        outcome = run.run()
    finally:
        rig.close()
    assert outcome.status == "complete"
    plan = run.plans[0]
    n = len(plan.raster.rows)
    assert [r.row for r in rows] == [BASELINE_ROW, WARMUP_ROW, *range(n)]
    assert {r.laser for r in rows} == {2} and {r.rows for r in rows} == {n}
    # Exactly what went to disk, block by block.
    data = read_run(outcome.lasers[0].path).scan_data()
    for block in rows:
        assert len(block.samples) == int(np.sum(data.row == block.row))
        assert all(s.row == block.row for s in block.samples)
    assert len(maps) == 1
    result, mapped = maps[0]
    assert result.laser == 2 and result.status == "complete"
    assert mapped.grid.values.shape[0] == n


def test_a_failing_display_never_ends_a_run(machine, tmp_path):
    clock = ScaledClock(20.0)
    rig, machine = make(machine, clock)
    said, calls = [], []

    def broken(block):
        calls.append(block.row)
        raise RuntimeError("canvas gone")

    def broken_map(result, mapped):
        raise RuntimeError("canvas gone")

    run = Session(ScanDevices(rig.marlin, rig.laser, rig.smu), machine,
                  clock, request(rig), tmp_path, simulated=True,
                  provenance={"commit": "test"}, say=said.append,
                  on_row=broken, on_map=broken_map)
    try:
        outcome = run.run()
    finally:
        rig.close()
    assert outcome.status == "complete"
    assert len(calls) == 1  # left out after the first failure
    assert sum("row display failed" in line for line in said) == 1
    assert sum("map display failed" in line for line in said) == 1
    assert outcome.lasers[0].png is not None


def test_each_laser_maps_with_its_own_range(machine, tmp_path):
    """D15 revised: lasers 100x apart in brightness need their own
    ranges. The file says which, and the SMU's current limit follows."""
    clock = ScaledClock(20.0)
    rig, machine = make(machine, clock)
    prepared = []
    original = rig.smu.prepare

    def watch(**kwargs):
        prepared.append((kwargs.get("current_range_a"),
                         kwargs.get("current_limit_a")))
        original(**kwargs)

    rig.smu.prepare = watch
    req = replace(request(rig, lasers=(2, 3)),
                  laser_ranges_a={3: 650e-6, 2: 180e-3})
    try:
        outcome = session(rig, machine, clock, req, tmp_path).run()
    finally:
        rig.close()
    assert outcome.status == "complete"
    assert prepared == [(180e-3, 180e-3), (650e-6, 650e-6)]
    for result, (want, _) in zip(outcome.lasers, prepared, strict=True):
        header = read_run(result.path).header
        assert header["current_range_a"] == want
        assert header["current_limit_a"] == want
    summary = json.loads((outcome.folder / "run.json").read_text())
    assert summary["request"]["laser_ranges_a"] == {"3": 650e-6,
                                                    "2": 180e-3}
    assert [p["current_range_a"] for p in summary["plans"]] == [180e-3,
                                                               650e-6]


def test_a_range_for_a_laser_not_in_the_run_is_refused(machine):
    clock = ScaledClock(20.0)
    rig, machine = make(machine, clock)
    try:
        req = replace(request(rig, lasers=(2,)), laser_ranges_a={1: 650e-6})
        with pytest.raises(RunPlanError, match=r"laser\(s\) \[1\]"):
            plan_run(req, machine)
    finally:
        rig.close()


def test_the_current_limit_follows_the_range():
    from multilbic.run.rows import AUTORANGE_CURRENT_LIMIT_A, current_limit_for

    assert current_limit_for(25e-6) == 25e-6
    assert current_limit_for(180e-3) == 180e-3
    assert current_limit_for(None) == AUTORANGE_CURRENT_LIMIT_A == 1e-3
