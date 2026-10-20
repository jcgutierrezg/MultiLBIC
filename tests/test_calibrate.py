"""Placing moves, and corner calibration driven by a scripted operator."""

import json

import pytest

from multilbic.run.calibrate import CalibrationPrompt, load_calibration
from multilbic.run.motion import approach
from multilbic.run.rows import ScanDevices
from multilbic.sim.rig import Faults, SimRig
from multilbic.sim.sample import SyntheticSample


@pytest.fixture
def rig(machine, clock):
    rig = SimRig(machine, clock, SyntheticSample.default(2.0, 1.0),
                 (15.2, 16.1), Faults())
    rig.open()
    yield rig
    rig.close()


def test_approach_always_ends_moving_up(rig, machine):
    rig.marlin.home()
    approach(rig.marlin, machine, x=50.0, y=40.0, a=20.0, b=20.0)
    # Coming down from above still ends moving up: the stage sits half
    # the backlash below the motor on every axis.
    approach(rig.marlin, machine, x=45.0, y=35.0, a=10.0, b=12.0)
    stage = rig.fake_marlin.stage_position()
    assert stage["X"] == pytest.approx(45.0 - 0.05)
    assert stage["Y"] == pytest.approx(35.0 - 0.05)
    assert stage["A"] == pytest.approx(10.0 - 0.01)
    assert stage["B"] == pytest.approx(12.0 - 0.01)
    # A short move down is no exception.
    approach(rig.marlin, machine, a=9.99)
    assert rig.fake_marlin.stage_position()["A"] == pytest.approx(9.98)


def scripted(lines):
    queue = list(lines)
    out = []

    def read(prompt):
        if not queue:
            raise EOFError
        return queue.pop(0)

    return read, out.append, out


def test_scripted_calibration_matches_the_truth(rig, machine, tmp_path):
    truth = rig.perfect_calibration("cell 7")
    x, y = truth.corner_xy_mm
    path = tmp_path / "cal.json"
    read, write, out = scripted([
        "x+1", "step 0.25", "a-", "where",
        f"move x={x} y={y} a=17.5 b=17.5",
        "read",
        "here",
        "size 2 1",
        "trace",
        f"save {path}",
        "quit",
    ])
    prompt = CalibrationPrompt(
        ScanDevices(rig.marlin, rig.laser, rig.smu), machine,
        sample="cell 7", read=read, write=write,
    )
    prompt.start()
    assert rig.fake_laser.active == machine.geometry.reference_laser
    assert prompt.loop() == path
    prompt.stop()
    assert rig.fake_laser.active == 0
    assert not any(line.startswith("error") for line in out), out
    saved = load_calibration(path)
    assert saved.corner_xy_mm == pytest.approx(truth.corner_xy_mm, abs=1e-4)
    assert saved.corner_ab_mm == pytest.approx(truth.corner_ab_mm, abs=1e-4)
    assert (saved.width_mm, saved.height_mm) == (2.0, 1.0)
    assert json.loads(path.read_text())["schema"] == "multilbic-calibration/1"
    assert any(line.endswith(" nA") for line in out)  # 'read' answered
    # 'trace' ended back on the corner: the spot is really there, not
    # just where the numbers say.
    u, v = rig.spot_uv(rig.fake_marlin.stage_position(),
                       machine.geometry.reference_laser)
    assert (u, v) == pytest.approx((0.0, 0.0), abs=1e-6)


def test_mistakes_are_reported_not_fatal(rig, machine):
    read, write, out = scripted([
        "jump", "here", "trace", "save", "size 1", "x+50", "quit",
    ])
    prompt = CalibrationPrompt(
        ScanDevices(rig.marlin, rig.laser, rig.smu), machine,
        sample="s", read=read, write=write,
    )
    prompt.start()
    prompt.loop()
    errors = [line for line in out if line.startswith("error")]
    assert len(errors) == 5  # all but 'here'
    assert "unknown command" in errors[0]
    assert "limited" in errors[-1]


def test_check_puts_the_saved_corner_back(rig, machine, tmp_path):
    truth = rig.perfect_calibration("cell 7")
    read, write, out = scripted(["where", "quit"])
    prompt = CalibrationPrompt(
        ScanDevices(rig.marlin, rig.laser, rig.smu), machine,
        sample="cell 7", read=read, write=write,
    )
    prompt.start(check=truth)
    prompt.loop()
    position = rig.marlin.position()
    assert (position["X"], position["Y"]) == pytest.approx(truth.corner_xy_mm)
    u, v = rig.spot_uv(rig.fake_marlin.stage_position(),
                       machine.geometry.reference_laser)
    assert (u, v) == pytest.approx((0.0, 0.0), abs=1e-6)
