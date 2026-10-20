"""XY placement: calibration in one place, every laser's XY from it."""

import itertools

import pytest

from multilbic.scan.geometry import (
    Calibration,
    GeometryError,
    ab_to_xy,
    place,
    xy_to_ab,
)

DIRECTIONS = [
    (x, y)
    for x, y in itertools.product(("+A", "-A", "+B", "-B"), repeat=2)
    if x[1] != y[1]
]


@pytest.mark.parametrize(("x_along", "y_along"), DIRECTIONS)
def test_xy_and_ab_convert_both_ways(x_along, y_along):
    da, db = xy_to_ab(x_along, y_along, 1.5, -0.25)
    assert ab_to_xy(x_along, y_along, da, db) == pytest.approx((1.5, -0.25))
    # X moves along the axis it names, by the full amount.
    da, db = xy_to_ab(x_along, y_along, 1.0, 0.0)
    along = da if x_along[1] == "A" else db
    assert along == (1.0 if x_along[0] == "+" else -1.0)


def calibration(x_along="+A", y_along="+B"):
    return Calibration(
        sample="cell 7", reference_laser=2, reference_xy_mm=(75.6, 71.7),
        corner_xy_mm=(70.0, 65.0), corner_ab_mm=(17.5, 17.5),
        width_mm=10.0, height_mm=5.0, x_along=x_along, y_along=y_along,
    )


def test_reference_laser_places_the_centre_on_the_ab_centre():
    # Corner under the beam at X70 Y65; the centre is 5 and 2.5 mm
    # further along A and B, so XY moves that much more.
    placed = place(calibration(), (75.6, 71.7), (17.5, 17.5), 2)
    assert placed.xy_mm == pytest.approx((75.0, 67.5))
    assert placed.frame.origin_ab_mm == pytest.approx((12.5, 15.0))
    assert placed.frame.width_mm == 10.0


def test_another_laser_moves_xy_by_the_lasers_offset():
    two = place(calibration(), (75.6, 71.7), (17.5, 17.5), 2)
    one = place(calibration(), (79.6, 71.3), (17.5, 17.5), 1)
    assert one.xy_mm[0] - two.xy_mm[0] == pytest.approx(4.0)
    assert one.xy_mm[1] - two.xy_mm[1] == pytest.approx(-0.4)
    # The AB frame is the same for every laser.
    assert one.frame == two.frame


@pytest.mark.parametrize(("x_along", "y_along"), DIRECTIONS)
def test_placement_puts_the_corner_back_under_the_beam(x_along, y_along):
    cal = calibration(x_along, y_along)
    placed = place(cal, (75.6, 71.7), (17.5, 17.5), 2)
    # With XY at the placement and AB at the frame's origin, the carriage
    # point under the reference beam is the calibrated corner.
    da, db = xy_to_ab(
        x_along, y_along,
        placed.xy_mm[0] - 75.6, placed.xy_mm[1] - 71.7,
    )
    a0, b0 = placed.frame.origin_ab_mm
    assert (a0 + da, b0 + db) == pytest.approx(cal.corner_carriage_mm)


def test_calibration_round_trips():
    cal = calibration("-B", "+A")
    assert Calibration.from_dict(cal.to_dict()) == cal


def test_size_must_be_positive():
    with pytest.raises(GeometryError):
        Calibration("s", 2, (0, 0), (0, 0), (0, 0), 0.0, 1.0, "+A", "+B")
