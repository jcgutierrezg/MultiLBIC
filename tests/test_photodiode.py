"""The photodiode: its table, reaching it, and the simulated chip."""

import tomllib
from dataclasses import replace
from importlib import resources

import pytest

from multilbic.clock import ScaledClock
from multilbic.config.machine import MachineConfigError, parse
from multilbic.run.devices import open_sim
from multilbic.scan.photodiode import (
    OutOfReach,
    carriage_point,
    open_quarter_middle,
    reach,
)
from multilbic.sim.photodiode import WIDTH_PER_SIGMA, SimPhotodiode

# Where lasers 1-3 met the open quarter by eye (bench, 2026-10-29), A
# and B +5 mm onto today's coordinates (the home offset).
BENCH = {1: (100, 70, 38.2, 24.3), 2: (99.7, 79.3, 35, 15),
         3: (100, 80, 33.7, 12.6)}


def raw():
    text = resources.files("multilbic.config").joinpath(
        "machine.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)


# ---- the table ----


def test_the_table_loads(machine):
    pd = machine.photodiode
    assert pd is not None
    assert pd.channel == 2
    # Open towards A- and B- on the carriage as built: larger A and B
    # in the carriage frame, the stage's way of counting.
    assert (pd.open_a, pd.open_b) == ("-", "-")
    assert pd.open_signs == (1, 1)
    assert pd.chip_mm == pytest.approx(3.6)
    # The corner 2026-10-30 found was the can window's: an estimate again.
    assert not pd.measured


def test_the_open_quarter_is_where_the_light_was_found(machine):
    # Laser 2 found light at the open quarter's middle and the window's
    # far edge at (60.239, 23.062) (bench, 2026-10-30): the open quarter
    # lies between the corner and that edge.
    middle = open_quarter_middle(machine)
    corner = machine.photodiode.corner_ab_mm
    assert middle[0] > corner[0] and middle[1] > corner[1]
    assert middle[0] < 60.239 and middle[1] < 23.062


def test_the_table_is_optional():
    data = raw()
    del data["photodiode"]
    assert parse(data).photodiode is None


@pytest.mark.parametrize("key, value, message", [
    ("channel", 3, "not 1 or 2"),
    ("open_a", "left", "open_a"),
    ("blade_a_above_mm", -0.1, "negative"),
    ("chip_mm", 0, "positive"),
    ("spare", 1, "unknown"),
])
def test_bad_values_are_refused(key, value, message):
    data = raw()
    data["photodiode"][key] = value
    with pytest.raises(MachineConfigError, match=message):
        parse(data)


# ---- reaching it ----


def test_the_bench_positions_land_near_the_open_quarter(machine):
    middle = open_quarter_middle(machine)
    for n, xyab in BENCH.items():
        a, b = carriage_point(machine, n, xyab)
        assert a == pytest.approx(middle[0], abs=0.5)
        assert b == pytest.approx(middle[1], abs=0.5)


def test_reach_keeps_ab_central_and_x_at_its_end(machine):
    corner = machine.photodiode.corner_ab_mm
    r = reach(machine, 1, corner)
    x, y, a, b = r.xyab
    assert x == pytest.approx(machine.xy.travel_mm[0])
    assert b == pytest.approx(machine.ab.centre_mm[1])
    assert carriage_point(machine, 1, r.xyab) == pytest.approx(corner)
    # Laser 1 has 5.0 mm left above the corner along A.
    assert r.room_mm[1] == pytest.approx(4.988, abs=1e-3)
    for n in (2, 3, 4, 5, 6):
        r = reach(machine, n, corner)
        assert carriage_point(machine, n, r.xyab) == pytest.approx(corner)


def test_out_of_reach_says_by_how_much(machine):
    corner = machine.photodiode.corner_ab_mm
    with pytest.raises(OutOfReach, match="short by 0.312"):
        reach(machine, 1, corner, room_mm=5.3)


def test_reach_follows_reversed_and_swapped_axes(machine):
    swapped = replace(machine, geometry=replace(
        machine.geometry, x_along="-B", y_along="+A"))
    point = (40.0, 10.0)
    r = reach(swapped, 2, point)
    assert carriage_point(swapped, 2, r.xyab) == pytest.approx(point)


# ---- the simulated chip ----


def pd(**changes):
    base = SimPhotodiode(
        corner_mm=(50.0, 20.0), open_signs=(-1, -1), chip_mm=3.6,
        blade_a_above_mm=0.4, full_a={1: -1e-3}, sigma_mm={1: 0.02},
    )
    return replace(base, **changes)


def test_full_on_the_open_quarter_dark_behind_the_blades():
    p = pd()
    assert p.share(1, 49.1, 19.1) == pytest.approx(1.0)
    assert p.current(1, 49.1, 19.1) == pytest.approx(-1e-3)
    assert p.share(1, 51.0, 19.1) == pytest.approx(0.0, abs=1e-9)
    assert p.share(1, 49.1, 21.0) == pytest.approx(0.0, abs=1e-9)
    # Off the chip altogether.
    assert p.share(1, 47.0, 19.1) == pytest.approx(0.0, abs=1e-9)
    assert p.share(1, 50.0, 20.0) == pytest.approx(0.25, rel=1e-3)


def test_the_open_side_can_be_either():
    p = pd(open_signs=(1, 1))
    assert p.share(1, 50.9, 20.9) == pytest.approx(1.0)
    assert p.share(1, 49.1, 19.1) == pytest.approx(0.0, abs=1e-9)


def test_each_edge_has_its_own_spot_size():
    p = pd()
    lower = p.sigma_at(1, 0.0)
    upper = p.sigma_at(1, 0.4)
    assert lower == pytest.approx(0.02)
    assert upper == pytest.approx((0.02 ** 2 + (0.05 * 0.4) ** 2) ** 0.5)

    def width(axis):
        # 10-90 % across the blade edge, the other axis well inside.
        lo = hi = None
        for i in range(-4000, 4000):
            x = (50.0 if axis == 0 else 20.0) + i * 1e-5
            s = p.share(1, x, 19.1) if axis == 0 else p.share(1, 49.1, x)
            if lo is None and s < 0.9:
                lo = x
            if hi is None and s < 0.1:
                hi = x
        return hi - lo

    assert width(0) == pytest.approx(WIDTH_PER_SIGMA * lower, rel=0.01)
    assert width(1) == pytest.approx(WIDTH_PER_SIGMA * upper, rel=0.01)


def test_moving_the_focus_blurs_the_lower_edge():
    p = pd()
    sharp = p.sigma_at(1, 0.0)
    p.focus_mm[1] = 0.5
    assert p.sigma_at(1, 0.0) > sharp
    # Focused on the upper blade instead: that edge is now the sharp one.
    p.focus_mm[1] = 0.4
    assert p.sigma_at(1, 0.4) == pytest.approx(sharp)


def test_from_config_uses_each_lasers_spot(machine):
    p = SimPhotodiode.from_config(machine)
    assert p.corner_mm == machine.photodiode.corner_ab_mm
    laser1 = machine.laser(1)
    assert p.sigma_mm[1] == pytest.approx(
        laser1.spot_um / 1000 / WIDTH_PER_SIGMA)


# ---- in the rig ----


def test_the_rig_reads_it_on_its_channel(machine):
    conn = open_sim(machine, clock=ScaledClock(50.0), smu_channels=(1, 2))
    rig = conn.rig
    assert rig is not None and rig.photodiode is not None
    try:
        d = conn.devices
        d.marlin.home()
        x, y, a, b = reach(machine, 3, open_quarter_middle(machine)).xyab
        d.marlin.move_to(feed_mm_s=20.0, x=x, y=y, a=a, b=b)
        d.marlin.wait_idle()
        d.laser.select(3)
        t = conn.clock.now()
        assert rig._signal(2, t) == pytest.approx(rig.photodiode.full_a[3],
                                                  rel=0.01)
        # Channel 1 is the sample, nowhere near.
        assert abs(rig._signal(1, t)) < 1e-9
        d.laser.off()
        assert rig._signal(2, conn.clock.now()) == rig.photodiode.dark_a
    finally:
        conn.close()
