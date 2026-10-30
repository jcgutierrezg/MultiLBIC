"""Focus assist: passes across a blade edge while the focus is turned,
against the simulated photodiode, and what Done proposes."""

import threading

import pytest

from multilbic.clock import ScaledClock
from multilbic.run import commission
from multilbic.run.commission import Commissioner, CommissionRequest
from multilbic.run.devices import Connection
from multilbic.run.focus import FocusAssist, FocusRequest
from multilbic.run.motion import RunStopped
from multilbic.run.rows import ScanDevices
from multilbic.sim.photodiode import WIDTH_PER_SIGMA
from multilbic.sim.rig import Faults, SimRig
from multilbic.sim.sample import SyntheticSample

SHARP_SIGMA = 0.016  # a 41 um spot at its waist
BLURRED_MM = 2.0  # the waist this far off the blade: about 260 um


def rig_for(machine, *, faults=None):
    clock = ScaledClock(50.0, precise=True)
    rig = SimRig(machine, clock, SyntheticSample.default(), (15.0, 16.0),
                 faults or Faults(), smu_channels=(2,))
    rig.photodiode.sigma_mm[2] = SHARP_SIGMA
    rig.photodiode.focus_mm[2] = BLURRED_MM
    rig.open()
    return rig, Connection(ScanDevices(rig.marlin, rig.laser, rig.smu),
                           clock, True, rig=rig)


def width_at(rig, laser, z=0.0):
    return WIDTH_PER_SIGMA * rig.photodiode.sigma_at(laser, z)


def focus(machine, request, on_pass=lambda assist, rig, p: None, **rig_args):
    rig, conn = rig_for(machine, **rig_args)
    try:
        assist = FocusAssist(conn.devices, machine, conn.clock,
                             say=lambda _: None)
        result = assist.run_focus(request,
                                  on_pass=lambda p: on_pass(assist, rig, p))
        return rig, result
    finally:
        conn.close()


def test_the_widths_follow_the_focus_and_done_measures_again(machine,
                                                              monkeypatch):
    # Readings as far apart as the real SMU's (the simulated one answers
    # at once), so the feeds are the machine's.
    monkeypatch.setattr(commission, "MIN_READ_INTERVAL_S", 0.038)
    blurred = sharp = None

    def turn(assist, rig, p):
        nonlocal blurred, sharp
        if p.number == 4:
            blurred = width_at(rig, 2)
            rig.photodiode.focus_mm[2] = 0.0  # the operator turns it
            sharp = width_at(rig, 2)

    rig, result = focus(machine, FocusRequest(2, max_passes=9, read_s=0.3),
                        turn)
    passes = result.passes
    assert len(passes) == 9 and all(p.good for p in passes)
    for p in passes[:4]:
        assert p.width_mm == pytest.approx(blurred, rel=0.08)
    for p in passes[5:]:
        assert p.width_mm == pytest.approx(sharp, rel=0.15)
    # Faster while blurred, slower once sharp: about the same readings
    # and time a pass, either way.
    assert passes[2].feed_mm_s > 4 * passes[-1].feed_mm_s
    for p in (passes[2], passes[-1]):
        assert 60 <= p.readings <= 110
    assert passes[-1].best_mm == pytest.approx(sharp, rel=0.15)
    assert passes[-1].scatter_mm is not None
    # Up, down, up...
    assert [p.direction for p in passes[:3]] == [1, -1, 1]
    # Done: measured again, laser 2 moves (the corner stays), its spot
    # is the sharp one.
    p = result.proposal
    assert p is not None and p.reference == 0
    assert p.corner_ab_mm == machine.photodiode.corner_ab_mm
    assert set(p.xy_centre_mm) == {2}
    assert p.spot_um[2] == pytest.approx(sharp * 1000, rel=0.05)
    assert rig.fake_laser.active == 0
    assert not rig.fake_smu.enabled[2]


def test_a_beam_that_moves_is_followed(machine):
    def knock(assist, rig, p):
        if p.number == 3:
            x, y = rig.laser_xy_mm[2]
            rig.laser_xy_mm[2] = (x + 0.12, y)  # refocusing moved it

    _, result = focus(machine, FocusRequest(2, max_passes=7, read_s=0.3),
                      knock)
    before = [p.position_mm for p in result.passes[:3]]
    after = [p.position_mm for p in result.passes[4:]]
    assert all(p.good for p in result.passes)
    # The beam 0.12 mm along +X sees the edge 0.12 mm further along A
    # (x_along = +A): the stage has to go that much further to bring it
    # under the beam.
    shift = sum(after) / len(after) - sum(before) / len(before)
    assert shift == pytest.approx(0.12, abs=0.01)


def test_done_proposes_where_the_beam_went(machine):
    rig, conn = rig_for(machine)
    try:
        c = Commissioner(conn.devices, machine, conn.clock,
                         say=lambda _: None)
        before = c.run(CommissionRequest((3,), warmup_s=0.0, read_s=0.3))
    finally:
        conn.close()

    def knock(assist, rig, p):
        if p.number == 1:
            x, y = rig.laser_xy_mm[3]
            rig.laser_xy_mm[3] = (x - 0.2, y + 0.1)

    _, result = focus(machine, FocusRequest(3, max_passes=3, read_s=0.3),
                      knock)
    x0, y0 = before.proposal.xy_centre_mm[3]
    x1, y1 = result.proposal.xy_centre_mm[3]
    assert (x1 - x0, y1 - y0) == pytest.approx((-0.2, 0.1), abs=0.004)


def test_both_axes_alternate(machine):
    _, result = focus(machine, FocusRequest(1, axes=(0, 1), max_passes=4,
                                            read_s=0.3))
    assert [p.axis for p in result.passes] == [0, 1, 0, 1]
    assert [p.direction for p in result.passes] == [1, 1, -1, -1]
    # The B edge is the upper blade, 0.4 mm further from the waist.
    a, b = result.passes[0], result.passes[1]
    assert a.width_mm != pytest.approx(b.width_mm, rel=0.01)


def test_finish_from_another_thread(machine):
    rig, conn = rig_for(machine)
    assist = FocusAssist(conn.devices, machine, conn.clock,
                         say=lambda _: None)
    seen = []

    def on_pass(p):
        seen.append(p)
        if len(seen) == 2:
            threading.Thread(target=assist.finish).start()

    try:
        result = assist.run_focus(FocusRequest(2, read_s=0.3), on_pass)
    finally:
        conn.close()
    assert 2 <= len(result.passes) <= 3
    assert result.final is not None and result.proposal is not None


def test_stop_stops_with_everything_off(machine):
    rig, conn = rig_for(machine)
    assist = FocusAssist(conn.devices, machine, conn.clock,
                         say=lambda _: None)
    seen = []

    def on_pass(p):
        seen.append(p)
        if len(seen) == 2:
            threading.Thread(target=assist.request_stop).start()

    try:
        with pytest.raises(RunStopped):
            assist.run_focus(FocusRequest(2, read_s=0.3), on_pass)
        assert rig.fake_laser.active == 0
        assert not rig.fake_smu.enabled[2]
    finally:
        conn.close()
