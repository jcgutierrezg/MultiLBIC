"""The window, driven as an operator would, against the simulated machine.

Needs a display: Windows has one, Linux CI runs under xvfb. Skipped
where Tk can't open a window.
"""

import time
from dataclasses import replace

import pytest

from multilbic.clock import ScaledClock
from multilbic.gui.jogkeys import arrow_label, jog_for
from multilbic.gui.worker import MachineWorker, State
from multilbic.run.devices import open_sim
from multilbic.run.session import RunRequest
from multilbic.sim.rig import Faults
from multilbic.sim.scan import sim_machine

tk = pytest.importorskip("tkinter")

SIZE = (0.6, 0.2)
CORNER = (15.0, 16.0)


# ---- which way the arrows jog: no window needed ----


def test_arrows_move_the_spot_as_the_operator_sees_it(machine):
    # Bench, 2026-10-23: +A moves the spot left, +B down; X goes with A.
    assert jog_for("left", "ab", machine) == ("a", 1)
    assert jog_for("right", "ab", machine) == ("a", -1)
    assert jog_for("down", "ab", machine) == ("b", 1)
    assert jog_for("up", "xy", machine) == ("y", -1)
    assert jog_for("left", "xy", machine) == ("x", 1)
    assert arrow_label("left", "ab", machine) == "+A"


def test_arrows_follow_swapped_axes(machine):
    swapped = replace(machine, geometry=replace(
        machine.geometry, x_along="-B", y_along="+A"))
    # Left is +A, which Y moves along; down is +B, which -X moves along.
    assert jog_for("left", "xy", swapped) == ("y", 1)
    assert jog_for("down", "xy", swapped) == ("x", -1)


# ---- the window ----


class Window:
    def __init__(self, app, rig):
        self.app, self.rig = app, rig
        self.root = app.root

    def pump(self, until, timeout=60.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if until():
                return
            time.sleep(0.005)
        raise AssertionError(
            f"timed out; state {self.app.state}, "
            f"status {self.app.status_label.cget('text')!r}")

    def ready(self):
        """Wait until the worker is idle and the window has seen every
        event up to that point."""
        def settled():
            if self.app.worker.state is not State.IDLE:
                return False
            for event in self.app.worker.drain():
                self.app.handle(event)
            return self.app.state is State.IDLE
        self.pump(settled)

    def click(self, button):
        assert "disabled" not in button.state(), button
        button.invoke()
        self.ready()


@pytest.fixture(scope="module")
def tk_root():
    """One Tk for every window test: starting Tcl afresh for each test
    failed now and then on Windows ("couldn't read file init.tcl")."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def window(machine, tk_root, monkeypatch):
    import gc
    import tkinter.filedialog
    import tkinter.messagebox

    # A dialog nobody answers would wait on the developer's screen (it
    # did, 2026-10-27): every dialog fails the test unless the test
    # answers it with its own monkeypatch.setattr, which wins.
    def unexpected(name):
        def dialog(*args, **kwargs):
            raise AssertionError(f"unexpected dialog {name}: {args!r}")
        return dialog

    for module in (tkinter.messagebox, tkinter.filedialog):
        for name in dir(module):
            if name.startswith(("ask", "show")):
                monkeypatch.setattr(module, name, unexpected(name))

    from smuniversal_lab_suite.core.thread_guard import install_tk_guard

    from multilbic.gui import look
    from multilbic.gui.app import App

    guard = install_tk_guard(strict=False)
    faults = Faults()
    machine = sim_machine(machine, faults)
    holder = {}

    def connector():
        conn = open_sim(machine, clock=ScaledClock(20.0),
                        corner_carriage_mm=CORNER, size_mm=SIZE,
                        faults=faults)
        holder["rig"] = conn.rig
        return conn

    worker = MachineWorker(machine, connector, poll_s=0.05)
    top = tk.Toplevel(tk_root)
    # The worker's thread keeps the process alive until it is closed,
    # so it is closed whatever happens from here on.
    try:
        theme = look.make_theme(tk_root, mode="dark")
        app = App(top, machine, worker, simulated=True, theme=theme)
        worker.connect()
        w = Window(app, None)
        w.ready()
        w.rig = holder["rig"]
        yield w
    finally:
        worker.close()
        if _alive(top):
            top.destroy()
        # Collect the window's Tk variables here, on the Tk thread: left
        # to the garbage collector they can be freed on a worker thread,
        # which Tk refuses.
        gc.collect()
        guard.remove()
    # No worker thread ever read or set a Tk variable.
    assert not guard.violations, guard.violations


def focus(window, widget):
    """Give `widget` the keyboard, as a click would."""
    widget.focus_force()
    window.root.update()
    if window.root.focus_get() is not widget:
        pytest.skip("the window manager kept the keyboard focus elsewhere")


def test_connects_and_shows_the_devices(window):
    app = window.app
    assert app.connected
    assert app.state_label.cget("text") == "ready"
    for key, label in app.connection.ids.items():
        assert label.cget("text") not in ("not connected", "no answer"), key
    assert "disabled" in app.connection.connect_btn.state()
    assert "disabled" not in app.stop_btn.state()


def test_jogging_waits_for_home_then_moves_the_spot(window):
    app = window.app
    stage = app.stage
    left = stage.arrows["left"]
    assert "disabled" in left.state()
    assert stage.homed_label.cget("text") == "not homed"
    window.click(stage.home_btn)
    assert app.homed and stage.homed_label.cget("text") == ""
    x0 = float(stage.position["X"].cget("text"))
    window.click(left)  # XY mode, 0.1 mm: +X
    assert float(stage.position["X"].cget("text")) - x0 == pytest.approx(0.1)


def test_keys_jog_only_while_the_pad_has_them(window):
    app = window.app
    stage = app.stage
    window.click(stage.home_btn)
    x0 = float(stage.position["X"].cget("text"))
    # Typing 'a' in the Go-to field must not move anything.
    focus(window, stage.targets["X"])
    stage.targets["X"].event_generate("<KeyPress-a>")
    window.root.update()
    window.ready()
    assert float(stage.position["X"].cget("text")) == x0
    assert stage.targets["X"].get() == "a"
    focus(window, stage.pad)
    assert stage.keys_label.cget("text") == "keys on"
    stage.pad.event_generate("<KeyPress-Left>")
    window.pump(lambda: float(stage.position["X"].cget("text")) != x0)
    window.ready()
    assert float(stage.position["X"].cget("text")) - x0 == pytest.approx(0.1)
    # q to AB, e to the next step (1 mm), then down: +B by 1 mm.
    b0 = float(stage.position["B"].cget("text"))
    for key in ("q", "e"):
        stage.pad.event_generate(f"<KeyPress-{key}>")
    assert stage.pair.get() == "ab" and stage.step.get() == 1.0
    stage.pad.event_generate("<KeyPress-Down>")
    window.pump(lambda: float(stage.position["B"].cget("text")) != b0)
    window.ready()
    assert float(stage.position["B"].cget("text")) - b0 == pytest.approx(1.0)


def test_go_to_moves_and_bad_input_is_refused(window):
    stage = window.app.stage
    window.click(stage.home_btn)
    stage.targets["A"].insert(0, "12.5")
    window.click(stage.go_btn)
    assert float(stage.position["A"].cget("text")) == pytest.approx(12.5)
    stage.targets["B"].insert(0, "abc")
    stage.go_btn.invoke()
    assert "not a number" in window.app.status_label.cget("text")


def test_laser_buttons_and_escape(window):
    app = window.app
    lasers = app.lasers
    window.click(lasers.buttons[2])
    assert window.rig.fake_laser.active == 2
    assert str(lasers.buttons[2].cget("style")) == "Laser2.Lit.TButton"
    # Esc anywhere is Stop; while idle, Stop turns the laser off.
    focus(window, lasers.off_btn)
    lasers.off_btn.event_generate("<Escape>")
    window.pump(lambda: window.rig.fake_laser.active == 0)
    window.ready()
    assert str(lasers.buttons[2].cget("style")) == "TButton"


def test_readings_show_once_homed(window):
    app = window.app
    window.click(app.stage.home_btn)
    window.pump(lambda: app.lasers.current.cget("text").endswith("A"))


def test_closing_during_a_run_asks_then_stops_it(window, tmp_path,
                                                 monkeypatch):
    app = window.app
    asked = []
    monkeypatch.setattr(
        "multilbic.gui.app.messagebox.askyesno",
        lambda *a, **k: asked.append(a) or True,
    )
    request = RunRequest(window.rig.perfect_calibration("cell"), (2,),
                         0.01, 0.05, 2.0, baseline_s=0.5, warmup_s=0.0)
    assert app.worker.start_run(request, tmp_path, {"commit": "test"})
    # Until the run has begun (RunStarted), a close stops it before it
    # makes its folder - right, but not what this test is about; it
    # raced on a busy machine.
    window.pump(lambda: app.run_panel.running)
    app.close()
    assert asked
    window.pump(lambda: not window.root.winfo_exists()
                if _alive(window.root) else True, timeout=60)
    assert app.worker.state is State.DISCONNECTED
    assert window.rig.fake_laser.active == 0
    (folder,) = tmp_path.iterdir()
    assert "stopped" in (folder / "run.json").read_text()


def _alive(root):
    try:
        return bool(root.winfo_exists())
    except tk.TclError:
        return False


# ---- the sample column ----


def calibrate_through_the_panels(window, tmp_path, monkeypatch):
    """Start, find the corner, size, trace, save: as an operator would,
    with the corner typed into Go to instead of jogged to."""
    app = window.app
    cal = app.calibration_panel
    truth = window.rig.perfect_calibration("cell")
    window.click(cal.start_btn)
    assert window.rig.fake_laser.active == 2
    cal.sample.set("cell")
    stage = app.stage
    for axis, value in zip("XYAB", (*truth.corner_xy_mm, *truth.corner_ab_mm),
                           strict=True):
        stage.targets[axis].delete(0, "end")
        stage.targets[axis].insert(0, f"{value:.6f}")
    window.click(stage.go_btn)
    window.click(cal.here_btn)
    cal.width.insert(0, f"{SIZE[0]:g}")
    cal.height.insert(0, f"{SIZE[1]:g}")
    window.click(cal.size_btn)
    window.click(cal.trace_btn)
    path = tmp_path / "cal" / "cell.json"
    monkeypatch.setattr("multilbic.gui.sample_panels.filedialog"
                        ".asksaveasfilename", lambda **k: str(path))
    window.click(cal.save_btn)
    assert path.exists()
    return truth, path


def test_calibrating_through_the_panels(window, tmp_path, monkeypatch):
    app = window.app
    cal = app.calibration_panel
    assert "disabled" in cal.trace_btn.state()  # nothing to trace yet
    truth, path = calibrate_through_the_panels(window, tmp_path, monkeypatch)
    assert cal.calibration is not None
    assert cal.calibration.corner_xy_mm == pytest.approx(truth.corner_xy_mm,
                                                         abs=1e-4)
    assert cal.file_label.cget("text") == str(path)
    # The trace ended on the corner, and the preview draws the spot there.
    _, outline = cal.preview.outline
    assert cal.preview.spot_ab() == pytest.approx(outline[0], abs=1e-3)
    assert cal.preview.canvas.find_all()
    # The run setup now has a plan.
    window.pump(lambda: app.setup.plan is not None)
    assert "in all, homing included" in app.setup.plan_label.cget("text")
    assert "disabled" not in app.setup.start_btn.state()


def test_loading_a_calibration(window, tmp_path, monkeypatch):
    import json

    truth = window.rig.perfect_calibration("loaded cell")
    path = tmp_path / "loaded.json"
    path.write_text(json.dumps(
        {"schema": "multilbic-calibration/1", **truth.to_dict()}))
    monkeypatch.setattr("multilbic.gui.sample_panels.filedialog"
                        ".askopenfilename", lambda **k: str(path))
    cal = window.app.calibration_panel
    window.click(cal.load_btn)
    assert cal.sample.get() == "loaded cell"
    assert cal.width.get() == "0.6"
    # Re-planned once typing would have paused.
    window.pump(lambda: window.app.setup.plan is not None)
    # Nothing moved: loading is not homing.
    assert not window.app.homed


def test_a_bad_field_blocks_start(window, tmp_path, monkeypatch):
    calibrate_through_the_panels(window, tmp_path, monkeypatch)
    setup = window.app.setup
    # The plan is made again 150 ms after the last change. Wait for the
    # one from the calibration first: until then the plan is the "no
    # calibration yet" one, which a wait for "no plan" would take for the
    # pitch's (seen on the slower ARM CI runner).
    window.pump(lambda: setup.plan is not None)
    setup.fields["pitch_mm"].set("zero")
    window.pump(lambda: setup.plan is None
                and "pitch" in setup.plan_label.cget("text"))
    assert "disabled" in setup.start_btn.state()
    setup.fields["pitch_mm"].set("0.05")
    window.pump(lambda: setup.plan is not None)


def test_a_run_from_the_window(window, tmp_path, monkeypatch):
    calibrate_through_the_panels(window, tmp_path, monkeypatch)
    app = window.app
    setup = app.setup
    for key, value in (("baseline_s", "0.5"), ("warmup_s", "0")):
        setup.fields[key].set(value)
    out = tmp_path / "runs"
    setup.out.set(str(out))
    asked = []
    offered = []
    monkeypatch.setattr(
        "multilbic.gui.sample_panels.messagebox.askokcancel",
        lambda title, text, **k: asked.append(text) or True,
    )
    # Laser 2's range is not checked: Start offers the check (D25); this
    # run starts anyway.
    monkeypatch.setattr(
        "multilbic.gui.sample_panels.messagebox.askyesnocancel",
        lambda title, text, **k: offered.append(text) or False,
    )
    window.pump(lambda: setup.plan is not None
                and setup.plan.request.warmup_s == 0)
    setup.start_btn.invoke()
    assert offered and "laser(s) 2" in offered[0]
    assert asked and "Lasers 2" in asked[0]
    window.pump(lambda: app.state is State.RUNNING)
    # Everything but Stop is off while it runs.
    assert "disabled" in app.stage.home_btn.state()
    assert "disabled" in setup.start_btn.state()
    assert "disabled" not in app.stop_btn.state()
    window.pump(lambda: app.state is State.IDLE, timeout=120)
    (folder,) = out.iterdir()
    assert folder.name.endswith("_cell")
    assert '"status": "complete"' in (folder / "run.json").read_text()
    assert "run complete" in app.status_label.cget("text")
    # The run column: the finished map in laser 2's tab, the bar full.
    run = app.run_panel
    window.pump(lambda: run.tabs[2].final)
    assert run.headline.cget("text") == "Run complete"
    assert float(run.bar.cget("value")) == pytest.approx(1.0)
    assert run.timing.cget("text").startswith("took")
    assert "serpentine shift" in run.tabs[2].caption.cget("text")
    assert run.live[2].rows_done == 4
    assert run.folder == folder
    assert "disabled" not in run.folder_btn.state()

    # And an earlier run's file opens in a tab of its own.
    csv = folder / "laser2_519nm.csv"
    monkeypatch.setattr("multilbic.gui.run_panel.filedialog"
                        ".askopenfilename", lambda **k: str(csv))
    tabs = len(run.notebook.tabs())
    run.open_btn.invoke()
    window.pump(lambda: len(run.notebook.tabs()) == tabs + 1)
    assert "opened" in app.status_label.cget("text")


def test_cancelling_start_starts_nothing(window, tmp_path, monkeypatch):
    calibrate_through_the_panels(window, tmp_path, monkeypatch)
    monkeypatch.setattr(
        "multilbic.gui.sample_panels.messagebox.askyesnocancel",
        lambda *a, **k: False)  # start anyway, past the ranges offer
    monkeypatch.setattr(
        "multilbic.gui.sample_panels.messagebox.askokcancel",
        lambda *a, **k: False)
    window.app.setup.out.set(str(tmp_path / "runs"))
    start = window.app.setup.start_btn
    window.pump(lambda: "disabled" not in start.state())  # else vacuous
    window.click(start)
    assert not (tmp_path / "runs").exists()


def test_the_laser_a_run_lights_shows(window, tmp_path, monkeypatch):
    from multilbic.gui.worker import RowEvent
    from multilbic.run.rows import RowDone

    lasers = window.app.lasers
    window.app.handle(RowEvent(RowDone(3, -1, 4, ())))  # baseline: off
    assert lasers.lit == 0
    window.app.handle(RowEvent(RowDone(3, 0, 4, ())))
    assert lasers.lit == 3
    assert str(lasers.buttons[3].cget("style")) == "Laser3.Lit.TButton"


def test_laser_colours_follow_the_wavelength():
    from multilbic.gui.spectrum import ink_on, needs_ring, wavelength_colour

    # As the old script showed them: blue, green, red, a deeper red,
    # then dark into the infrared.
    blue, green, red, deep = (wavelength_colour(nm)
                              for nm in (444, 519, 652, 676))
    assert blue.startswith("#00") and blue.endswith("ff")
    assert green[3:5] == "ff" and red == "#f50000"
    assert int(deep[1:3], 16) < int(red[1:3], 16)
    ir = [wavelength_colour(nm) for nm in (785, 848)]
    assert all(needs_ring(c) for c in ir)
    assert ink_on(green) == "#000000" and ink_on(ir[1]) == "#ffffff"


def test_the_header_draws_the_revolver(window):
    import math

    canvas = window.app.emblem
    # A ring, six laser dots and the spot.
    items = canvas.find_all()
    assert len(items) == 1 + 6 + 1
    # The dots run 1 to 6 clockwise, each opposite its servo partner.
    size = int(canvas.cget("width"))
    angles = []
    for item in items[1:7]:
        x0, y0, x1, y1 = canvas.coords(item)
        x, y = (x0 + x1) / 2 - size / 2, size / 2 - (y0 + y1) / 2
        angles.append(math.degrees(math.atan2(y, x)) % 360)
    steps = [(a - b) % 360 for a, b in zip(angles[:-1], angles[1:], strict=True)]
    assert all(step == pytest.approx(60, abs=1) for step in steps), angles
    for k in range(3):
        assert (angles[k] - angles[k + 3]) % 360 == pytest.approx(180, abs=1)


def test_the_plan_tab_follows_the_setup(window, tmp_path, monkeypatch):
    calibrate_through_the_panels(window, tmp_path, monkeypatch)
    app = window.app
    view = app.run_panel.plan_view
    setup = app.setup
    window.pump(lambda: view.plan is not None)
    assert view.headline.cget("text").startswith("1 laser, about ")
    assert len(view.canvas.find_all()) > 10  # sample, rows, markers
    # A laser's row in the table, with its colour; homing; the total.
    texts = [w.cget("text") for w in view.table.winfo_children()]
    assert any("Laser 2 (519 nm)" in t for t in texts)
    assert any("Homing" in t for t in texts) and "Whole run" in texts
    # Laser 2's spot is 41 um: a 50 um pitch leaves a strip, said so.
    assert "rim" in view.notes.cget("text")
    # Editing a field brings the Plan tab to the front and re-plans.
    setup.fields["pitch_mm"].set("0.03")
    window.pump(lambda: view.plan is not None
                and view.plan.request.pitch_mm == 0.03)
    assert app.run_panel.notebook.select() == str(view.frame)
    assert "every point is lit" in view.notes.cget("text")
    # A second laser: two close-ups, two table rows.
    setup.laser_vars[3].set(True)
    setup.changed()
    window.pump(lambda: view.plan is not None and len(view.plan.plans) == 2)
    assert view.headline.cget("text").startswith("2 lasers")


def test_checking_ranges_from_the_window(window, tmp_path, monkeypatch):
    calibrate_through_the_panels(window, tmp_path, monkeypatch)
    app = window.app
    cal, setup = app.calibration_panel, app.setup
    view = app.run_panel.plan_view
    assert setup.range_source[2] == "guess"
    asked = []
    monkeypatch.setattr("multilbic.gui.sample_panels.messagebox.askokcancel",
                        lambda title, text, **k: asked.append(text) or True)
    window.click(cal.ranges_btn)
    assert asked and "Lasers 2" in asked[0]
    window.pump(lambda: setup.range_source[2] == "checked")
    assert setup.range_vars[2].get() == "25u"
    assert cal.ranges_label.cget("text").startswith("2: 25u (checked")
    window.pump(lambda: setup.plan is not None
                and setup.plan.range_sources.get(2) == "checked")
    texts = [w.cget("text") for w in view.table.winfo_children()]
    assert "25u (checked)" in texts
    # Nothing left to offer at Start: no dialog but the confirm. (The
    # fixture fails the test on any other.)
    monkeypatch.setattr("multilbic.gui.sample_panels.messagebox.askokcancel",
                        lambda *a, **k: False)
    setup.start_btn.invoke()
    window.ready()


def test_ranges_set_by_hand_and_the_default(window, tmp_path, monkeypatch):
    calibrate_through_the_panels(window, tmp_path, monkeypatch)
    setup = window.app.setup
    setup.laser_vars[3].set(True)
    setup._lasers_changed()
    # A range picked for laser 3 is its own from then on.
    setup.range_vars[3].set("650u")
    setup._range_set(3)
    assert setup.range_source[3] == "set"
    # The default moves only the guesses: laser 2, not laser 3.
    setup.current_range.set("1u")
    setup._default_changed()
    assert setup.range_vars[2].get() == "1u"
    assert setup.range_vars[3].get() == "650u"
    window.pump(lambda: setup.plan is not None
                and setup.plan.request.range_for(2) == 1e-6)
    request = setup.plan.request
    assert request.range_for(3) == 650e-6
    assert setup.plan.guessed() == [2]
    # The step-up box reaches the run.
    setup.step_up.set(False)
    setup.changed()
    window.pump(lambda: setup.plan is not None
                and not setup.plan.request.step_up)
    assert "a clip ends the run" in " ".join(setup.plan.notes)


def test_start_offers_the_check_for_guessed_ranges(window, tmp_path,
                                                   monkeypatch):
    calibrate_through_the_panels(window, tmp_path, monkeypatch)
    app = window.app
    checked_for = []
    monkeypatch.setattr(
        "multilbic.gui.sample_panels.messagebox.askyesnocancel",
        lambda title, text, **k: True)  # yes: check them first
    monkeypatch.setattr(
        app.calibration_panel, "check_ranges",
        lambda lasers=None: checked_for.append(lasers))
    # Start is enabled once the plan is made, which Run setup does a
    # moment after the calibration changes: on a slow CI runner the
    # press came first and did nothing (2026-10-28).
    window.pump(lambda: "disabled" not in app.setup.start_btn.state())
    window.click(app.setup.start_btn)
    assert checked_for == [[2]]
    assert app.state is State.IDLE  # no run started


def test_the_ranges_line_follows_the_ticked_lasers(window, tmp_path,
                                                   monkeypatch):
    """However the lasers get ticked: a laser missing from the line
    would map with the default range without saying so."""
    calibrate_through_the_panels(window, tmp_path, monkeypatch)
    setup = window.app.setup
    for n in (1, 3):
        setup.laser_vars[n].set(True)  # not a click
    setup.changed()
    window.pump(lambda: setup.plan is not None and len(setup.plan.plans) == 3)
    assert setup._ranges_shown == [1, 2, 3]
    combos = [w for w in setup._range_widgets]
    assert len(combos) == 3
