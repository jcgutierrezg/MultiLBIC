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
    assert "in all, plus homing" in plan.lines[-1]
    assert plan.estimate_s > 60  # the warm-up alone
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
