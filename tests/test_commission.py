"""`multilbic commission`: finding each laser and its spot with the
photodiode, against the simulated machine, and what it proposes."""

import threading
from importlib import resources

import pytest

from multilbic import cli
from multilbic.clock import ScaledClock
from multilbic.config.machine import load
from multilbic.run.commission import (
    Commissioner,
    CommissionError,
    CommissionRequest,
    Edge,
    LaserCommission,
    Proposal,
    apply_proposal,
    propose,
)
from multilbic.run.devices import Connection
from multilbic.run.motion import RunStopped
from multilbic.run.reading import summarise
from multilbic.run.rows import ScanDevices
from multilbic.sim.rig import Faults, SimRig
from multilbic.sim.sample import SyntheticSample

QUICK = dict(warmup_s=0.0, read_s=0.3)


def machine_text():
    return resources.files("multilbic.config").joinpath(
        "machine.toml").read_text(encoding="utf-8")


def rig_for(machine, *, offsets=None, corner_shift=(0.0, 0.0),
            faults=None, spot_sigma=None):
    clock = ScaledClock(50.0, precise=True)
    laser_xy = {
        n: (machine.laser(n).xy_centre_mm[0] + dx,
            machine.laser(n).xy_centre_mm[1] + dy)
        for n, (dx, dy) in (offsets or {}).items()}
    rig = SimRig(machine, clock, SyntheticSample.default(), (15.0, 16.0),
                 faults or Faults(), laser_xy_mm=laser_xy,
                 smu_channels=(2,))
    c = rig.photodiode.corner_mm
    rig.photodiode.corner_mm = (c[0] + corner_shift[0],
                                c[1] + corner_shift[1])
    if spot_sigma is not None:
        for n in rig.photodiode.sigma_mm:
            rig.photodiode.sigma_mm[n] = spot_sigma
    rig.open()
    return rig, Connection(ScanDevices(rig.marlin, rig.laser, rig.smu),
                           clock, True, rig=rig)


def commission(machine, lasers, *, new_corner=False, **rig_args):
    rig, conn = rig_for(machine, **rig_args)
    try:
        c = Commissioner(conn.devices, machine, conn.clock,
                         say=lambda _: None)
        return rig, c.run(CommissionRequest(tuple(lasers), **QUICK,
                                            new_corner=new_corner))
    finally:
        conn.close()


# ---- end to end ----


def test_it_recovers_wrong_laser_positions_the_corner_and_the_spots(machine):
    offsets = {1: (0.1, -0.2), 3: (-0.25, 0.15)}
    faults = Faults(smu_stamp_lag_s=0.0186)
    # The photodiode moved since it was measured: a new corner.
    rig, result = commission(machine, (2, 1, 3), offsets=offsets,
                             corner_shift=(0.2, -0.3), faults=faults,
                             new_corner=True)
    p = result.proposal
    assert p is not None and p.reference == 2
    for n in (1, 2, 3):
        dx, dy = offsets.get(n, (0.0, 0.0))
        old = machine.laser(n).xy_centre_mm
        assert p.xy_centre_mm[n] == pytest.approx(
            (old[0] + dx, old[1] + dy), abs=0.003)
        # The spot along A: the blade at the sample's height.
        assert p.spot_um[n] == pytest.approx(machine.laser(n).spot_um,
                                             rel=0.05)
        r = result.lasers[n]
        # Up minus down: 20 um of AB backlash, the lag under a micrometre.
        assert r.edges[0].split_mm == pytest.approx(0.020, abs=0.004)
        # The B edge is 0.4 mm above focus: wider.
        assert r.edges[1].width_mm > r.edges[0].width_mm
        assert r.power_a == pytest.approx(rig.photodiode.full_a[n], rel=0.02)
        assert not r.searched and not r.warnings
    # The corner, in the frame placing moves give: XY arrives moving up,
    # half its 0.1 mm backlash short, as calibration's corner does.
    true = rig.photodiode.corner_mm
    assert p.corner_ab_mm == pytest.approx((true[0] + 0.05, true[1] + 0.05),
                                           abs=0.003)
    assert rig.fake_laser.active == 0


def test_a_placeholder_laser_is_found_by_searching(machine):
    rig, result = commission(machine, (2, 4), offsets={4: (2.5, -1.5)},
                             new_corner=True)
    r = result.lasers[4]
    assert r.searched
    old = machine.laser(4).xy_centre_mm
    assert result.proposal.xy_centre_mm[4] == pytest.approx(
        (old[0] + 2.5, old[1] - 1.5), abs=0.003)


def test_a_corner_beyond_reach_says_so(machine):
    from dataclasses import replace

    # X stopping at 100, as Marlin's compiled limit did: laser 1 reaches
    # A 60.43 on the carriage, short of the open quarter's middle with
    # the corner 1.5 mm past its 58.44 (59.94 + 0.9).
    short = replace(machine, xy=replace(machine.xy, travel_mm=(100.0, 120.0)))
    with pytest.raises(CommissionError, match="beyond its reach"):
        commission(short, (1,), corner_shift=(1.5, 0.0))


def test_no_light_anywhere_near_fails_clearly(machine):
    with pytest.raises(CommissionError, match="no light"):
        commission(machine, (2,), offsets={2: (10.0, 10.0)})


def estimated(machine):
    """`machine` with its photodiode corner still an estimate."""
    from dataclasses import replace

    return replace(machine, photodiode=replace(machine.photodiode,
                                               measured=False))


def measured(machine):
    """`machine` with its photodiode corner measured."""
    from dataclasses import replace

    return replace(machine, photodiode=replace(machine.photodiode,
                                               measured=True))


def test_a_measured_corner_stays_and_the_reference_laser_moves(machine):
    # Laser 2's beam moved (refocused): the photodiode did not, so laser
    # 2's position follows, against a run before it moved.
    machine = measured(machine)
    _, before = commission(machine, (2, 3))
    _, after = commission(machine, (2, 3), offsets={2: (0.3, -0.2)})
    p0, p1 = before.proposal, after.proposal
    assert p1.reference == 0
    assert p1.corner_ab_mm == machine.photodiode.corner_ab_mm
    dx = p1.xy_centre_mm[2][0] - p0.xy_centre_mm[2][0]
    dy = p1.xy_centre_mm[2][1] - p0.xy_centre_mm[2][1]
    assert (dx, dy) == pytest.approx((0.3, -0.2), abs=0.003)
    # Laser 3 did not move.
    assert p1.xy_centre_mm[3] == pytest.approx(p0.xy_centre_mm[3], abs=0.003)
    assert any("stays" in line for line in p1.lines(machine))


def test_without_the_reference_laser_there_is_no_proposal(machine):
    _, result = commission(estimated(machine), (3,))
    assert result.proposal is None
    assert "reference" in result.error


def test_stop_stops_with_everything_off(machine):
    rig, conn = rig_for(machine)
    c = Commissioner(conn.devices, machine, conn.clock, say=lambda _: None)
    timer = threading.Timer(0.5, c.request_stop)
    timer.start()
    try:
        with pytest.raises(RunStopped):
            c.run(CommissionRequest((2, 1, 3), **QUICK))
        assert rig.fake_laser.active == 0
        assert not rig.fake_smu.enabled[2]
    finally:
        timer.cancel()
        conn.close()


# ---- what it proposes ----


def result_with(laser, corner, width=0.04):
    r = LaserCommission(laser)
    r.edges[0] = Edge(0, corner[0], width, 0.02, ())
    r.edges[1] = Edge(1, corner[1], width * 1.5, 0.02, ())
    return r


def test_each_laser_moves_by_its_view_of_the_corner(machine):
    results = {2: result_with(2, (54.8, 18.5)),
               1: result_with(1, (55.0, 18.4))}
    for p in (propose(estimated(machine), results),
              propose(machine, results, new_corner=True)):
        assert p.reference == 2
    assert p.corner_ab_mm == (54.8, 18.5)
    assert p.xy_centre_mm[2] == machine.laser(2).xy_centre_mm
    x, y = machine.laser(1).xy_centre_mm
    assert p.xy_centre_mm[1] == pytest.approx((x + 0.2, y - 0.1))
    assert p.spot_um[1] == pytest.approx(40.0)


def test_a_measured_corner_needs_no_reference(machine):
    machine = measured(machine)
    corner = machine.photodiode.corner_ab_mm
    p = propose(machine, {3: result_with(3, (corner[0] + 0.1, corner[1]))})
    assert p.reference == 0
    x, y = machine.laser(3).xy_centre_mm
    assert p.xy_centre_mm[3] == pytest.approx((x + 0.1, y))
    with pytest.raises(CommissionError, match="reference"):
        propose(estimated(machine), {3: result_with(3, corner)})


def test_writing_keeps_everything_else(machine):
    p = Proposal(2, (54.81234, 18.4), {1: (79.71, 71.2), 4: (51.9, 41.5)},
                 {1: 63.24, 4: 70.0})
    text = machine_text()
    out = apply_proposal(text, p, "2026-10-29")
    old_lines, new_lines = text.splitlines(), out.splitlines()
    # One line more: laser 4 had no spot_um.
    assert len(new_lines) == len(old_lines) + 1
    changed = [n for n in new_lines if n not in old_lines]
    assert all(line.endswith("# commission 2026-10-29") for line in changed)
    assert "corner_ab_mm = [54.812, 18.400]  # commission 2026-10-29" in out
    assert "spot_um = 63.2  # commission 2026-10-29" in out


def test_the_voltage_check_reports_the_offset_state(machine):
    rig, conn = rig_for(machine)
    try:
        c = Commissioner(conn.devices, machine, conn.clock,
                         say=lambda _: None)
        r = LaserCommission(2)
        c._check_voltage(r, summarise(0, [1e-9] * 3, volts=[0.27] * 3),
                         "dark")
        assert r.warnings and "offset state" in r.warnings[0]
        c._check_voltage(r, summarise(0, [1e-9] * 3, volts=[0.0003] * 3),
                         "dark")
        assert len(r.warnings) == 1
    finally:
        conn.close()


# ---- the command ----


def test_cli_writes_only_with_write(tmp_path, capsys):
    path = tmp_path / "machine.toml"
    path.write_text(machine_text(), encoding="utf-8", newline="")
    before = path.read_bytes()
    args = ["--machine", str(path), "commission", "--sim", "--lasers", "2,3",
            "--new-corner",
            "--warmup", "0", "--read", "0.3", "--speedup", "50",
            "--sim-offset", "3=0.1,0.1", "--out", str(tmp_path / "runs")]
    assert cli.main(args) == 0
    assert path.read_bytes() == before
    out = capsys.readouterr().out
    assert "proposed for machine.toml" in out
    (folder,) = (tmp_path / "runs").iterdir()
    assert (folder / "commission.json").exists()
    assert (folder / "machine-proposed.toml").exists()

    assert cli.main(args + ["--write", "--yes"]) == 0
    written = path.read_bytes()
    assert b"\r\n" not in written
    machine = load(path)
    assert machine.photodiode.measured
    x, y = load().laser(3).xy_centre_mm
    assert machine.laser(3).xy_centre_mm == pytest.approx(
        (x + 0.1, y + 0.1), abs=0.003)


def test_a_failed_run_still_saves_what_it_read(tmp_path):
    import json

    # Laser 2 10 mm off: no light anywhere it searches.
    args = ["commission", "--sim", "--lasers", "2", "--warmup", "0",
            "--read", "0.3", "--speedup", "50", "--sim-offset", "2=10,10",
            "--out", str(tmp_path / "runs")]
    with pytest.raises(SystemExit, match="no light"):
        cli.main(args)
    (folder,) = (tmp_path / "runs").iterdir()
    report = json.loads((folder / "commission.json").read_text())
    assert "no light" in report["error"]
    assert report["proposal"] is None
    laser = report["lasers"]["2"]
    assert laser["first_dark"] is not None and laser["first"] is None
    assert not (folder / "machine-proposed.toml").exists()


def test_light_found_on_the_edge_of_the_spot(machine):
    # Laser 3 0.95 mm off along Y (+B), with a 250 um spot: the open
    # quarter's middle, where the light is first found, sits 0.1 mm past
    # the blade along A, on the spot's tail (laser 4, bench 2026-10-30,
    # was on the edge). The range chosen from that sliver is too small:
    # a pass that clips goes again on a larger one, and the edges, the
    # widths and the power come out as with the laser where it should
    # be. (On the bench the first coarse pass found no edge there, and
    # is tried again from further into the open quarter.)
    wide = 0.1
    _, base = commission(machine, (3,), spot_sigma=wide)
    _, off = commission(machine, (3,), offsets={3: (0.0, 0.95)},
                        spot_sigma=wide)
    b0, r = base.lasers[3], off.lasers[3]
    assert abs(r.first.median_a) < 0.2 * abs(r.power_a)
    assert any("range's limit" in w for w in r.warnings)
    assert r.edges[1].position_mm - b0.edges[1].position_mm == pytest.approx(
        0.95, abs=0.005)
    assert r.edges[0].position_mm == pytest.approx(b0.edges[0].position_mm,
                                                   abs=0.005)
    for k in (0, 1):
        assert r.edges[k].width_mm == pytest.approx(b0.edges[k].width_mm,
                                                    rel=0.03)
    assert r.power_a == pytest.approx(b0.power_a, rel=0.01)


def test_a_coarse_pass_that_starts_past_the_far_edge(machine):
    # Laser 3 0.8 mm off the other way along Y: found 1.65 mm into the
    # open quarter, so the coarse pass starts 1 mm further, past the
    # chip's far edge, and crosses two edges. Only the blade's, from the
    # brightest point on, is fitted.
    _, base = commission(machine, (3,))
    _, off = commission(machine, (3,), offsets={3: (0.0, -0.8)})
    b0, r = base.lasers[3], off.lasers[3]
    assert not r.searched
    assert r.edges[1].position_mm - b0.edges[1].position_mm == pytest.approx(
        -0.8, abs=0.005)
    assert r.edges[1].width_mm == pytest.approx(b0.edges[1].width_mm,
                                                rel=0.05)
