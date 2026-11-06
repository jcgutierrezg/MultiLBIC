"""A run folder as one set of maps: every laser on one grid, and what
the viewer needs from the files around them."""

import shutil

import numpy as np
import pytest

from multilbic.clock import ScaledClock
from multilbic.config import load
from multilbic.run.rows import ScanDevices
from multilbic.run.session import RunRequest, Session
from multilbic.scan.binning import Grid
from multilbic.scan.mapping import build_map
from multilbic.sim.rig import Faults, SimRig
from multilbic.sim.sample import SyntheticSample
from multilbic.sim.scan import sim_machine
from multilbic.store.runfile import read_run
from multilbic.store.runfolder import (
    RunFolderError,
    on_grid,
    read_folder,
    shared_grid,
)

CORNER = (15.0, 16.0)
#: As conftest.SIM_SPEED: simulated seconds per real second.
SIM_SPEED = 20.0


@pytest.fixture(scope="module")
def run_folder(tmp_path_factory):
    """A finished two-laser run on the simulator, made once."""
    clock = ScaledClock(SIM_SPEED)
    faults = Faults()
    machine = sim_machine(load(), faults)
    rig = SimRig(machine, clock, SyntheticSample.default(0.3, 0.15), CORNER,
                 faults)
    rig.open()
    try:
        request = RunRequest(
            rig.perfect_calibration("two lasers"), (1, 2),
            pixel_mm=0.01, pitch_mm=0.05, speed_mm_s=2.0,
            baseline_s=0.5, warmup_s=0.0, note="runfolder test")
        session = Session(ScanDevices(rig.marlin, rig.laser, rig.smu),
                          machine, clock, request,
                          tmp_path_factory.mktemp("runs"), simulated=True,
                          provenance={"commit": "test"})
        outcome = session.run()
    finally:
        rig.close()
    assert outcome.status == "complete"
    return outcome.folder


def copy_of(folder, tmp_path):
    return shutil.copytree(folder, tmp_path / folder.name)


def test_every_laser_on_one_grid(run_folder):
    run = read_folder(run_folder)
    assert run.lasers == [1, 2]
    assert run.status == "complete"
    assert run.sample == "two lasers"
    assert run.note == "runfolder test"
    assert run.simulated
    assert run.run_id == run_folder.name
    assert run.calibration is not None
    assert run.problems == {} and run.attempts == []
    assert run.stack().shape == (2, *run.grid.shape)
    for n, m in run.maps.items():
        alone = build_map(read_run(m.path).scan_data()).grid
        # The same run's lasers share the frame: the grid is each map's
        # own, and the values are its own, untouched.
        assert run.grid.same_as(alone)
        np.testing.assert_array_equal(m.values, alone.values)
        assert m.laser == n and m.complete
        assert m.wavelength_nm == pytest.approx(
            load().laser(n).wavelength_nm)
        assert m.current_range_a is not None
    assert run.grid.extent_mm == pytest.approx((0.0, 0.3, 0.0, 0.15))


def test_a_laser_file_opens_its_folder(run_folder):
    first = next(run_folder.glob("laser*_*nm.csv"))
    assert read_folder(first).lasers == [1, 2]


def test_attempts_listed_bad_files_reported(run_folder, tmp_path):
    folder = copy_of(run_folder, tmp_path)
    laser1 = next(folder.glob("laser1_*nm.csv"))
    shutil.copy(laser1, folder / laser1.name.replace(".csv", "_25u.csv"))
    (folder / "laser3_652nm.csv").write_text("not a run\n", encoding="utf-8")
    (folder / "run.json").write_text("{broken", encoding="utf-8")
    run = read_folder(folder)
    assert run.lasers == [1, 2]
    assert [(a.laser, a.range_text) for a in run.attempts] == [(1, "25u")]
    assert set(run.problems) == {"laser3_652nm.csv", "run.json"}
    assert run.summary is None
    # With no run.json the status comes from the files.
    assert run.status == "complete"


def test_a_run_still_going_opens(run_folder, tmp_path):
    """A file cut after its first rows, as one being written: the rows so
    far are mapped, the rest are empty."""
    folder = copy_of(run_folder, tmp_path)
    laser2 = next(folder.glob("laser2_*nm.csv"))
    lines = laser2.read_text(encoding="utf-8").splitlines(keepends=True)
    rows = [k for k, line in enumerate(lines) if line.startswith("#row: ")]
    laser2.write_text("".join(lines[:rows[2]]), encoding="utf-8")
    run = read_folder(folder)
    m = run.maps[2]
    assert not m.complete and m.status == "incomplete"
    assert run.status == "complete"  # run.json, as the copy left it
    done = ~np.isnan(m.values).all(axis=1)
    assert done[:2].all() and not done[2:].any()


def test_no_maps_is_an_error(tmp_path):
    with pytest.raises(RunFolderError, match="no laser maps"):
        read_folder(tmp_path)
    with pytest.raises(RunFolderError, match="no such folder"):
        read_folder(tmp_path / "missing")
    (tmp_path / "laser1_444nm.csv").write_text("junk\n", encoding="utf-8")
    with pytest.raises(RunFolderError, match="could be read"):
        read_folder(tmp_path)


def _grid(values, pixel, pitch):
    values = np.asarray(values, dtype=float)
    return Grid(values, np.ones_like(values, dtype=int), pixel, pitch)


def test_different_grids_meet_on_the_finest():
    coarse = _grid([[1.0, 2.0], [3.0, 4.0]], pixel=0.02, pitch=0.1)
    fine = _grid(np.zeros((2, 3)), pixel=0.01, pitch=0.05)
    shared = shared_grid([coarse, fine])
    assert (shared.pixel_mm, shared.pitch_mm) == (0.01, 0.05)
    # The area both cover between them: 0.04 x 0.2 mm.
    assert shared.shape == (4, 4)
    np.testing.assert_array_equal(
        on_grid(coarse, shared),
        [[1, 1, 2, 2], [1, 1, 2, 2], [3, 3, 4, 4], [3, 3, 4, 4]])
    placed = on_grid(fine, shared)
    # The fine map covers 0.03 x 0.1 mm of it; the rest is empty.
    np.testing.assert_array_equal(np.isnan(placed), [
        [False, False, False, True], [False, False, False, True],
        [True, True, True, True], [True, True, True, True]])


def test_alike_grids_are_kept_as_they_are():
    a = _grid(np.arange(6).reshape(2, 3), pixel=0.01, pitch=0.05)
    b = _grid(np.ones((2, 3)), pixel=0.01, pitch=0.05)
    shared = shared_grid([a, b])
    assert shared.same_as(a) and shared.same_as(b)
    np.testing.assert_array_equal(on_grid(a, shared), a.values)
