"""The window's run setup, checked without a window."""

from dataclasses import replace

import pytest

from multilbic.clock import ScaledClock
from multilbic.gui.runform import FormError, RunForm, plan_form
from multilbic.sim.rig import Faults, SimRig
from multilbic.sim.sample import SyntheticSample


@pytest.fixture
def calibration(machine):
    rig = SimRig(machine, ScaledClock(20.0), SyntheticSample.default(2.0, 1.0),
                 (15.0, 16.0), Faults())
    return rig.perfect_calibration("cell 7")


def test_the_defaults_make_a_plan(machine, calibration):
    plan = plan_form(RunForm(), calibration, machine, simulated=True)
    assert plan.request.lasers == (2,)
    assert plan.request.pixel_mm == 0.01 and plan.request.warmup_s == 60
    assert plan.request.current_range_a == 25e-6
    assert plan.lines[0] == "cell 7: 2 x 1 mm"
    assert plan.lines[1].startswith("laser 2 (519 nm): 20 rows")
    assert "in all, homing included" in plan.lines[-1]
    assert plan.estimate_s > 60 + 28  # the warm-up and homing alone
    assert not plan.warnings


def test_each_bad_field_is_named(machine, calibration):
    for field, form in (
        ("calibration", None),
        ("lasers", RunForm(lasers=())),
        ("pixel", RunForm(pixel_mm="abc")),
        ("pitch", RunForm(pitch_mm="0")),
        ("speed", RunForm(speed_mm_s="-1")),
        ("warm-up", RunForm(warmup_s="-5")),
        ("baseline", RunForm(baseline_s="nan")),
    ):
        with pytest.raises(FormError) as caught:
            plan_form(form or RunForm(), None if form is None else calibration,
                      machine, simulated=True)
        assert caught.value.field == field, (field, caught.value)


def test_what_plan_run_refuses_is_shown(machine, calibration):
    machine = placeholders(machine, 4)
    with pytest.raises(FormError, match="placeholder"):
        plan_form(RunForm(lasers=(4,)), calibration, machine, simulated=True)
    assert plan_form(RunForm(lasers=(4,), allow_unmeasured=True),
                     calibration, machine, simulated=True)
    big = replace(calibration, width_mm=40.0)
    with pytest.raises(FormError, match="safe range"):
        plan_form(RunForm(), big, machine, simulated=True)


def test_the_real_machine_needs_its_directions_checked(machine, calibration):
    unchecked = replace(machine, geometry=replace(
        machine.geometry, directions_measured=False))
    assert plan_form(RunForm(), calibration, unchecked, simulated=True)
    with pytest.raises(FormError, match="directions_measured"):
        plan_form(RunForm(), calibration, unchecked, simulated=False)


def test_warnings(machine, calibration):
    plan = plan_form(RunForm(speed_mm_s="5.5", current_range="auto"),
                     calibration, machine, simulated=True)
    assert any("noisy" in w for w in plan.warnings)
    assert any("autoranging" in w for w in plan.warnings)


def test_the_preview_zooms_to_the_sample():
    from multilbic.gui.sample_panels import scale_bar_mm, view_box

    # No outline: AB's whole safe range.
    assert view_box(None, (17.5, 17.5), 0.0, 35.0) == (17.5, 17.5, 35.0)
    # A 2 x 1 mm sample: centred on it, with room round it.
    square = [(16.5, 17.0), (18.5, 17.0), (18.5, 18.0), (16.5, 18.0),
              (16.5, 17.0)]
    a, b, span = view_box(square, (18.5, 17.0), 0.0, 35.0)
    assert (a, b) == pytest.approx((17.5, 17.5))
    assert 2.0 < span < 4.0
    # The spot far away widens the view to keep it in sight.
    _, _, wide = view_box(square, (30.0, 17.0), 0.0, 35.0)
    assert wide > 13.5
    assert scale_bar_mm(3.0) == 1.0 and scale_bar_mm(35.0) == 10.0


# The 2026-10-26 bench run from the window: the cell's right edge,
# laser 2 at 1 mm/s, 40 rows, 60 s warm-up. It took 221 s, homing
# included.
BENCH_CALIBRATION = {
    "sample": "stdtest-redge", "reference_laser": 2,
    "reference_xy_mm": [75.6, 71.7], "corner_xy_mm": [67.1, 58.9],
    "corner_ab_mm": [15.5, 18.5], "size_mm": [2.0, 2.0],
    "x_along": "+A", "y_along": "+B",
}


def test_the_estimate_matches_the_bench_run(machine):
    from multilbic.scan.geometry import Calibration

    cal = Calibration.from_dict(BENCH_CALIBRATION)
    plan = plan_form(RunForm(speed_mm_s="1"), cal, machine, simulated=False)
    assert plan.estimate_s == pytest.approx(221, rel=0.05)


def test_the_estimate_follows_the_sample(machine):
    """Rows, travel and the map come from the sample; only homing and a
    laser's fixed cost are constants."""
    from multilbic.scan.geometry import Calibration

    small = Calibration.from_dict(BENCH_CALIBRATION)
    tall = replace(small, height_mm=4.0)
    wide = replace(small, width_mm=4.0)
    est = {name: plan_form(RunForm(speed_mm_s="1", warmup_s="0"), c,
                           machine, simulated=True).estimate.lasers[0]
           for name, c in (("small", small), ("tall", tall), ("wide", wide))}
    # Twice the rows, twice the row time.
    assert est["tall"].rows_s == pytest.approx(2 * est["small"].rows_s,
                                               rel=0.02)
    # Twice as long rows: more than the 2 mm extra at 1 mm/s per row.
    assert est["wide"].rows_s - est["small"].rows_s == pytest.approx(
        40 * 2.0, rel=0.05)
    # More samples, a longer map; the fixed costs stay.
    assert est["tall"].map_s > est["small"].map_s
    assert est["tall"].switch_s == est["small"].switch_s
    # A second laser moves XY from the first's placement, not from home.
    two = plan_form(RunForm(lasers=(2, 3), speed_mm_s="1"), small, machine,
                    simulated=True).estimate.lasers
    assert two[1].travel_s < two[0].travel_s


def test_eta_text():
    from multilbic.gui.runform import eta

    assert eta(45) == "45 s"
    assert eta(223) == "3 min 43 s"
    assert eta(3900) == "1 h 05 min"


def test_spot_against_pitch():
    from multilbic.gui.runform import spot_against_pitch

    assert "9 µm strip" in spot_against_pitch(41, 50)
    assert "just touch" in spot_against_pitch(41, 40)
    assert "every point is lit" in spot_against_pitch(65, 50)
    assert "faster for the same detail" in spot_against_pitch(244, 50)


def test_unmeasured_spots_share_one_note(machine, calibration):
    machine = placeholders(machine, 4, 5, 6)
    plan = plan_form(RunForm(lasers=(2, 4, 5, 6), allow_unmeasured=True),
                     calibration, machine, simulated=True)
    unmeasured = [n for n in plan.notes if "not measured" in n]
    assert unmeasured == ["lasers 4, 5, 6: spots not measured yet (the "
                          "photodiode measures them, Phase 6)"]


def placeholders(machine, *numbers):
    """`machine` with lasers `numbers` back to placeholders: unmeasured,
    no spot (all six were commissioned 2026-10-30)."""
    from dataclasses import replace as _replace

    lasers = tuple(_replace(laser, measured=False, spot_um=None)
                   if laser.number in numbers else laser
                   for laser in machine.lasers)
    return _replace(machine, lasers=lasers)


def test_the_version_is_the_running_codes():
    """Not the installed record, which `uv run --no-sync` leaves behind
    after a pull (the window showed 0.5.3 while running 0.5.13)."""
    import tomllib
    from pathlib import Path

    from multilbic.version import app_version

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert app_version() == expected["project"]["version"]


def test_ranges_per_laser_in_the_form(machine, calibration):
    plan = plan_form(RunForm(lasers=(1, 2, 3), current_range="25u",
                             laser_ranges={1: "650u", 3: "650u", 5: "1u"}),
                     calibration, machine, simulated=True)
    r = plan.request
    assert [r.range_for(n) for n in (1, 2, 3)] == [650e-6, 25e-6, 650e-6]
    assert 5 not in r.laser_ranges_a  # not in the run: dropped
    auto = plan_form(RunForm(lasers=(1, 2), laser_ranges={2: "auto"}),
                     calibration, machine, simulated=True)
    assert any("autoranging" in w for w in auto.warnings)
    with pytest.raises(FormError, match="no range"):
        plan_form(RunForm(laser_ranges={2: "2u"}), calibration, machine,
                  simulated=True)
