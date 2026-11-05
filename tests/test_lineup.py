"""The line-up: each laser's offset on the cell, from its map's edges."""

import dataclasses
from pathlib import Path

import pytest

from multilbic.clock import ScaledClock
from multilbic.config import load
from multilbic.config.machine import parse
from multilbic.run.lineup import (
    CellEdges,
    Edge,
    LineUpError,
    apply_offsets,
    centred_patch,
    line_up,
    read_lineup,
)
from multilbic.run.rows import ScanDevices
from multilbic.run.session import RunRequest, Session
from multilbic.sim.rig import Faults, SimRig
from multilbic.sim.sample import SyntheticSample
from multilbic.sim.scan import CORNER_CARRIAGE_MM, sim_machine

MACHINE_TOML = (Path(__file__).resolve().parents[1]
                / "multilbic" / "config" / "machine.toml")


def _edges(n, u, v, shift=120.0):
    return CellEdges(n, Edge(u, 0.005, 12, 0.05), Edge(v, 0.005, 30, 0.05),
                     shift)


def test_offsets_put_each_laser_on_the_reference(machine):
    ref = machine.geometry.reference_laser
    edges = {ref: _edges(ref, 0.300, 0.300),
             1: _edges(1, 0.340, 0.280),
             5: _edges(5, 0.300, 0.300)}
    lineup = line_up(edges, {}, machine)
    assert lineup.error is None
    assert lineup.proposal[ref] == (0.0, 0.0)
    assert lineup.proposal[5] == pytest.approx((0.0, 0.0))
    # x_along +A, y_along +B: a map 40 um further along u is a beam
    # 40 um further along X.
    assert lineup.proposal[1] == pytest.approx((0.040, -0.020))
    assert lineup.spread_um() == pytest.approx((40.0, 20.0))


def test_offsets_add_to_those_the_run_used(machine):
    ref = machine.geometry.reference_laser
    edges = {ref: _edges(ref, 0.300, 0.300), 1: _edges(1, 0.310, 0.300)}
    lineup = line_up(edges, {1: (0.020, 0.005), ref: (0.0, 0.0)}, machine)
    assert lineup.proposal[1] == pytest.approx((0.030, 0.005))


def test_an_unclear_edge_leaves_that_laser_out(machine):
    ref = machine.geometry.reference_laser
    vague = CellEdges(1, Edge(0.3, 0.09, 12, 0.05), Edge(0.3, 0.005, 30, 0.05),
                      None)
    lineup = line_up({ref: _edges(ref, 0.3, 0.3), 1: vague}, {}, machine)
    assert 1 not in lineup.proposal
    assert "along u" in lineup.left_out[1]


def test_no_reference_no_proposal(machine):
    lineup = line_up({1: _edges(1, 0.3, 0.3)}, {}, machine)
    assert lineup.proposal == {}
    assert "reference" in (lineup.error or "")


def test_offsets_are_written_into_machine_toml(machine):
    text = MACHINE_TOML.read_text(encoding="utf-8")
    out = apply_offsets(text, {1: (0.0123, -0.0456), 3: (0.0, 0.0)},
                        "2026-11-05")
    import tomllib

    written = parse(tomllib.loads(out))
    assert written.laser(1).cell_offset_xy_mm == pytest.approx((0.012, -0.046))
    assert written.laser(3).cell_offset_xy_mm == (0.0, 0.0)
    assert "# lineup 2026-11-05" in out
    # Everything else as it was, comments included.
    assert out.count("\n#") == text.count("\n#")
    # Written again, the key is replaced, not added.
    again = apply_offsets(out, {1: (0.001, 0.002)}, "2026-11-06")
    assert again.count("cell_offset_xy_mm") == out.count("cell_offset_xy_mm")


def test_an_offset_moves_where_runs_place_the_laser(machine):
    laser = dataclasses.replace(machine.laser(1),
                                cell_offset_xy_mm=(0.03, -0.01))
    assert laser.on_cell_xy_mm == pytest.approx(
        (laser.xy_centre_mm[0] + 0.03, laser.xy_centre_mm[1] - 0.01))


def test_the_patch_is_centred_on_the_calibrations_corner(machine):
    from multilbic.scan.geometry import Calibration

    cal = Calibration("cell", 3, (1.0, 2.0), (50.0, 40.0), (20.0, 20.0),
                      10.0, 10.0, "+A", "+B")
    patch = centred_patch(cal, 1.2)
    assert patch.corner_ab_mm == pytest.approx((19.4, 19.4))
    assert (patch.width_mm, patch.height_mm) == (1.2, 1.2)
    assert patch.corner_xy_mm == cal.corner_xy_mm


def test_no_files_no_lineup(tmp_path, machine):
    with pytest.raises(LineUpError):
        read_lineup(tmp_path, machine)


def _lineup_run(out, machine, faults, lasers=(1, 3, 5), truth=None):
    """A line-up run with `machine`'s offsets, on a rig whose beams land
    as `truth` (machine.toml when the run began, with `faults`) says."""
    clock = ScaledClock(5.0, precise=True)
    sample = SyntheticSample.corner((0.5, 0.5))
    rig = SimRig(truth or machine, clock, sample, CORNER_CARRIAGE_MM, faults)
    cal = rig.perfect_calibration("corner")
    # The operator set the corner on the cell's corner.
    a, b = cal.corner_ab_mm
    cal = dataclasses.replace(cal, corner_ab_mm=(a + 0.5, b + 0.5))
    request = RunRequest(centred_patch(cal, 0.6), lasers, 0.01, 0.025, 2.0,
                         baseline_s=0.5, warmup_s=0.0, allow_unmeasured=True)
    rig.open()
    try:
        from multilbic.bench.report import provenance

        session = Session(ScanDevices(rig.marlin, rig.laser, rig.smu),
                          machine, clock, request, out, simulated=True,
                          provenance=provenance())
        outcome = session.run()
    finally:
        rig.close()
    assert outcome.status == "complete"
    return read_lineup(session.folder, machine)


@pytest.mark.sim_timing
def test_a_simulated_lineup_finds_and_corrects_each_offset(tmp_path):
    # Lasers 1 and 5 land off on the cell but not on the photodiode.
    faults = Faults(cell_offset_xy_mm=((1, 0.030, -0.020),
                                       (5, -0.025, 0.040)))
    machine = sim_machine(load(), faults)
    assert machine.geometry.reference_laser == 3
    first = _lineup_run(tmp_path / "first", machine, faults)
    assert first.error is None, first.lines(machine)
    assert first.proposal[3] == (0.0, 0.0)

    def beyond(n, dx, dy):
        # The fault adds to the offset machine.toml already has.
        x, y = machine.laser(n).cell_offset_xy_mm
        return x + dx, y + dy

    assert first.proposal[1] == pytest.approx(beyond(1, 0.030, -0.020),
                                              abs=0.005)
    assert first.proposal[5] == pytest.approx(beyond(5, -0.025, 0.040),
                                              abs=0.005)

    # Written, the maps land on each other; the beams stay where they are.
    corrected = dataclasses.replace(machine, lasers=tuple(
        dataclasses.replace(laser, cell_offset_xy_mm=first.proposal.get(
            laser.number, laser.cell_offset_xy_mm))
        for laser in machine.lasers))
    second = _lineup_run(tmp_path / "second", corrected, faults,
                         truth=machine)
    su, sv = second.spread_um()
    assert su is not None and su < 6
    assert sv is not None and sv < 6
    # And it proposes what is already there.
    assert second.proposal[1] == pytest.approx(first.proposal[1], abs=0.005)
