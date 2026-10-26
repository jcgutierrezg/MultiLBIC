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
def window(machine, tk_root):
    import gc

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
    assert str(lasers.buttons[2].cget("style")) == "Lit.TButton"
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
    window.pump(lambda: app.state is State.RUNNING)
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
