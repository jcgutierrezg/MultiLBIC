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


class FakeKeys:
    """Key presses from a list; counts flushes."""

    def __init__(self, keys):
        self.keys = list(keys)
        self.flushes = 0

    def read(self):
        return self.keys.pop(0)

    def flush(self):
        self.flushes += 1


def test_key_mode_jogs_toggles_and_steps(rig, machine):
    import contextlib

    keys = FakeKeys([
        "d", "d", "W",      # X +0.1 twice, Y +0.1 (case doesn't matter)
        "e", "a",           # step 1 mm, X -1
        "q", "e", "e",      # AB, step 10 -> back to 0.1
        "s", "",            # B -0.1; an arrow key is ignored
        "\x1b",             # Esc: back to typed commands
    ])
    read, write, out = scripted(["keys", "where", "quit"])
    prompt = CalibrationPrompt(
        ScanDevices(rig.marlin, rig.laser, rig.smu), machine,
        sample="s", read=read, write=write,
        keys=lambda: contextlib.nullcontext(keys),
    )
    prompt.start()
    start = rig.marlin.position()
    prompt.loop()
    end = rig.marlin.position()
    assert end["X"] - start["X"] == pytest.approx(0.1 + 0.1 - 1.0)
    assert end["Y"] - start["Y"] == pytest.approx(0.1)
    assert end["A"] == pytest.approx(start["A"])
    assert end["B"] - start["B"] == pytest.approx(-0.1)
    assert keys.flushes == 5  # after every jog
    assert "[AB, 0.1 mm]" in out
    assert out[-1].startswith("X")  # 'where' after leaving key mode
    assert not any(line.startswith("error") for line in out), out


def test_a_jog_out_of_range_in_key_mode_is_only_reported(rig, machine):
    import contextlib

    # From A at the centre (17.5), three 10 mm steps up run past the
    # 35 mm safe limit on the second.
    keys = FakeKeys(["q", "e", "e", "d", "d", "\r"])
    read, write, out = scripted(["keys", "quit"])
    prompt = CalibrationPrompt(
        ScanDevices(rig.marlin, rig.laser, rig.smu), machine,
        sample="s", read=read, write=write,
        keys=lambda: contextlib.nullcontext(keys),
    )
    prompt.start()
    prompt.loop()
    assert rig.marlin.position()["A"] == pytest.approx(27.5)
    errors = [line for line in out if line.startswith("error")]
    assert len(errors) == 1 and "outside" in errors[0]


# ---- the Calibrator, as the GUI drives it ----


def calibrator(rig, machine, **kw):
    from multilbic.run.calibrate import Calibrator

    return Calibrator(ScanDevices(rig.marlin, rig.laser, rig.smu), machine,
                      sample="s", **kw)


def test_an_approach_that_is_stopped_does_not_move(rig, machine):
    import threading

    from multilbic.run.motion import RunStopped

    rig.marlin.home()
    stop = threading.Event()
    stop.set()
    before = rig.marlin.position()
    with pytest.raises(RunStopped):
        approach(rig.marlin, machine, x=50.0, a=20.0, stop=stop)
    assert rig.marlin.position() == before


def test_calibrator_refuses_bad_input_before_moving(rig, machine):
    cal = calibrator(rig, machine)
    cal.start()
    before = cal.position()
    with pytest.raises(ValueError, match="limited"):
        cal.jog("x", 20.5)
    with pytest.raises(ValueError, match="no axis"):
        cal.jog("z", 1.0)
    with pytest.raises(ValueError, match="some of"):
        cal.move(z=1.0)
    with pytest.raises(ValueError, match="positive"):
        cal.set_size(0.0, 1.0)
    with pytest.raises(ValueError, match="no corner"):
        cal.trace()
    assert cal.position() == before
    cal.shut_down()


def test_calibrator_outline_is_the_sample_as_a_run_places_it(rig, machine):
    truth = rig.perfect_calibration("cell 7")
    cal = calibrator(rig, machine)
    cal.adopt(truth)
    (x, y), outline = cal.outline_ab()
    a0, b0 = outline[0]
    assert outline[-1] == outline[0]
    assert outline[2] == pytest.approx((a0 + 2.0, b0 + 1.0))
    # Centred on the AB centre, so the whole of AB is free round it.
    ca, cb = machine.ab.centre_mm
    assert (a0 + 1.0, b0 + 0.5) == pytest.approx((ca, cb))
    # Under the reference laser at that XY, the spot is on the corner.
    rig.marlin.home()
    approach(rig.marlin, machine, x=x, y=y, a=a0, b=b0)
    u, v = rig.spot_uv(rig.fake_marlin.stage_position(),
                       machine.geometry.reference_laser)
    assert (u, v) == pytest.approx((0.0, 0.0), abs=1e-3)


def test_halt_stops_a_trace_and_the_next_jog_works(rig, machine):
    import threading
    import time

    from multilbic.run.motion import RunStopped

    truth = rig.perfect_calibration("cell 7")
    said = []
    cal = calibrator(rig, machine, say=said.append)
    cal.start(check=truth)
    errors = []

    def trace():
        try:
            cal.trace()
        except RunStopped as exc:
            errors.append(exc)

    worker = threading.Thread(target=trace)
    worker.start()
    deadline = time.monotonic() + 30
    while "tracing the outline" not in said and time.monotonic() < deadline:
        time.sleep(0.005)
    time.sleep(0.05)  # 1 s simulated: part way along the first side
    cal.halt()
    worker.join(30)
    assert not worker.is_alive()
    assert len(errors) == 1, "the trace should end in RunStopped"
    assert not rig.fake_marlin.moving()
    # Stopped part way round, not carried on to the corner.
    u, v = rig.spot_uv(rig.fake_marlin.stage_position(),
                       machine.geometry.reference_laser)
    assert (u, v) != pytest.approx((0.0, 0.0), abs=1e-3)
    # The laser is left as it was: calibration goes on.
    assert rig.fake_laser.active == machine.geometry.reference_laser
    before = cal.position()
    after = cal.jog("x", 0.5)
    assert after["X"] - before["X"] == pytest.approx(0.5)
    cal.shut_down()
    assert rig.fake_laser.active == 0
