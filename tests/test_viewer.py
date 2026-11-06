"""The viewer: its arithmetic without a window, then the window on a
simulated run, driven as a person would (the mouse included).

The window part needs a display: Windows has one, Linux CI runs under
xvfb. Skipped where Tk can't open a window.
"""

import shutil
import time

import numpy as np
import pytest

from multilbic.gui import viewtools
from multilbic.store.image import image_data
from multilbic.store.runfolder import SharedGrid, read_folder

GRID = SharedGrid((np.arange(10) + 0.5) * 0.01, (np.arange(4) + 0.5) * 0.05,
                  0.01, 0.05)


# ---- the arithmetic ----


@pytest.mark.parametrize("view", [("right", "up"), ("left", "down"),
                                  ("up", "left"), ("down", "right")])
def test_plot_points_turn_back_into_u_v(view):
    x, y = viewtools.to_xy(view, 0.3, 0.1)
    assert viewtools.to_uv(view, x, y) == (0.3, 0.1)
    # u along the plot's x only when u is drawn across.
    assert (x == 0.3) == viewtools.u_horizontal(view)


def test_the_pixel_under_a_point():
    values = np.arange(40.0).reshape(4, 10)
    assert viewtools.pixel_at(GRID, 0.0, 0.0) == (0, 0)
    assert viewtools.pixel_at(GRID, 0.0999, 0.1999) == (3, 9)
    assert viewtools.pixel_at(GRID, 0.1, 0.0) is None
    assert viewtools.pixel_at(GRID, -0.001, 0.0) is None
    assert viewtools.value_at(values, GRID, 0.025, 0.06) == 12.0
    assert viewtools.value_at(values, GRID, 0.5, 0.06) is None


def test_a_profile_crosses_every_pixel_on_its_way():
    values = np.zeros((4, 10))
    values[:, 5:] = 1.0  # a step at u = 0.05 mm
    p = viewtools.profile(values, GRID, (0.0, 0.1), (0.1, 0.1))
    assert p.length_mm == pytest.approx(0.1)
    assert p.distance_mm[0] == 0.0
    assert p.distance_mm[-1] == pytest.approx(0.1)
    # A point every half pixel: none of the ten pixels is skipped.
    assert np.diff(p.distance_mm).max() <= 0.005 + 1e-12
    step = p.distance_mm[np.argmax(p.values > 0.5)]
    assert step == pytest.approx(0.05, abs=0.005)
    # Off the map: NaN, not a value from the edge.
    past = viewtools.profile(values, GRID, (0.05, 0.1), (0.15, 0.1))
    assert np.isnan(past.values[past.distance_mm > 0.051]).all()


def test_colour_limits():
    values = np.linspace(0.0, 1.0, 1001)
    values[0], values[-1] = -50.0, 50.0  # two wild pixels
    lo, hi = viewtools.auto_limits(values)
    assert -0.1 < lo < 0.05 and 0.95 < hi < 1.1
    assert viewtools.full_limits(values) == (-50.0, 50.0)
    flat = viewtools.full_limits(np.full(5, -2e-6))
    assert flat[0] < -2e-6 < flat[1]
    assert viewtools.auto_limits(np.full(3, np.nan)) is None


@pytest.mark.parametrize("biggest, unit", [
    (1.19e-3, "mA"), (8e-4, "µA"), (6e-5, "µA"), (4e-7, "nA"),
    (3e-13, "pA"), (np.nan, "pA")])
def test_a_map_is_shown_in_a_unit_that_suits_it(biggest, unit):
    assert viewtools.display_unit(np.array([0.0, -biggest]))[0] == unit


# ---- the window ----

tk = pytest.importorskip("tkinter")


@pytest.fixture(scope="module")
def tk_root():
    """One Tk for every window test, as in test_gui.py."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def viewer(machine, tk_root, monkeypatch):
    import tkinter.filedialog
    import tkinter.messagebox

    from multilbic.gui import look
    from multilbic.gui.viewer import Viewer

    # Every dialog fails the test unless the test answers it itself.
    def unexpected(name):
        def dialog(*args, **kwargs):
            raise AssertionError(f"unexpected dialog {name}: {args!r}")
        return dialog

    for module in (tkinter.messagebox, tkinter.filedialog):
        for name in dir(module):
            if name.startswith(("ask", "show")):
                monkeypatch.setattr(module, name, unexpected(name))

    top = tk.Toplevel(tk_root)
    top.geometry("1400x850")
    theme = look.make_theme(tk_root, mode="dark")
    v = Viewer(top, machine, theme=theme)
    yield v
    top.destroy()


def wait_loaded(v, timeout=30.0):
    deadline = time.monotonic() + timeout
    v.root.update()
    while v.loading:
        if time.monotonic() > deadline:
            raise AssertionError("the folder never finished loading")
        v.root.update()
        time.sleep(0.01)
    v.root.update()


def opened(v, folder):
    v.load(folder)
    wait_loaded(v)
    assert v.run is not None, v.status_label.cget("text")
    return v.run


def test_a_run_opens_on_its_first_laser(viewer, run_folder):
    run = opened(viewer, run_folder)
    assert sorted(viewer.laser_buttons) == [1, 2]
    assert viewer.laser == 1
    shown = viewer.image.get_array()
    expected = image_data(run.maps[1].values, viewer.view, viewer.unit[1])
    np.testing.assert_allclose(np.ma.filled(shown, np.nan), expected)
    assert "two lasers" in viewer.run_info.cget("text")
    assert "complete" in viewer.caption.cget("text")
    assert "opened" in viewer.status_label.cget("text")
    assert "disabled" not in viewer.reload_btn.state()


def test_picking_a_laser_and_colour_limits(viewer, run_folder):
    run = opened(viewer, run_folder)
    viewer.show_laser(2)
    assert viewer.laser == 2 and viewer.laser_var.get() == 2
    scale = viewer.unit[1]
    auto = viewtools.auto_limits(run.maps[2].values)
    assert viewer.clim() == pytest.approx((auto[0] / scale, auto[1] / scale))

    viewer.limits_mode.set("full")
    viewer._mode_changed()
    full = viewtools.full_limits(run.maps[2].values)
    assert viewer.clim() == pytest.approx((full[0] / scale, full[1] / scale))

    viewer.lo_var.set("-5")
    viewer.hi_var.set("1")
    viewer.apply_typed()
    assert viewer.limits_mode.get() == "set"
    assert viewer.clim() == pytest.approx((-5.0, 1.0))
    # Typed limits are kept, in amps, for the next laser too.
    viewer.show_laser(1)
    assert viewer.limits_a == pytest.approx((-5 * scale, 1 * scale))

    viewer.lo_var.set("2")
    viewer.apply_typed()  # not above the first: refused, nothing changes
    assert "above" in viewer.status_label.cget("text")
    assert viewer.limits_a == pytest.approx((-5 * scale, 1 * scale))


def test_keys_pick_a_laser(viewer, run_folder):
    opened(viewer, run_folder)
    viewer.root.focus_force()
    viewer.root.event_generate("<Key>", keysym="2")
    viewer.root.update()
    assert viewer.laser == 2
    viewer.root.event_generate("<Key>", keysym="9")  # no laser 9: stays
    viewer.root.update()
    assert viewer.laser == 2


def _mouse(viewer, name, u, v, button=1):
    """A matplotlib mouse event at u, v on the drawn map."""
    from matplotlib.backend_bases import MouseEvent

    x, y = viewtools.to_xy(viewer.view, u, v)
    px, py = viewer.axes.transData.transform((x, y))
    event = MouseEvent(name, viewer.canvas, px, py, button=button)
    viewer.canvas.callbacks.process(name, event)


def test_the_cursor_reads_the_map(viewer, run_folder):
    run = opened(viewer, run_folder)
    viewer.canvas.draw()
    _mouse(viewer, "motion_notify_event", 0.105, 0.075)
    text = viewer.readout.cget("text")
    assert "u 0.105 mm, v 0.075 mm" in text
    value = viewtools.value_at(run.maps[1].values, run.grid, 0.105, 0.075)
    from multilbic.gui.look import amps
    assert (amps(value) if np.isfinite(value) else "no samples") in text


def test_a_dragged_line_gives_a_profile_that_follows_the_laser(viewer,
                                                               run_folder):
    run = opened(viewer, run_folder)
    viewer.canvas.draw()
    _mouse(viewer, "button_press_event", 0.02, 0.075)
    _mouse(viewer, "motion_notify_event", 0.15, 0.075)
    _mouse(viewer, "button_release_event", 0.28, 0.075)
    assert viewer.line_uv is not None
    (u0, v0), (u1, v1) = viewer.line_uv
    assert (u0, v0, u1, v1) == pytest.approx((0.02, 0.075, 0.28, 0.075),
                                             abs=1e-3)
    p = viewer.profile
    assert p.length_mm == pytest.approx(0.26, abs=1e-3)
    np.testing.assert_array_equal(
        p.values, viewtools.profile(run.maps[1].values, run.grid,
                                    *viewer.line_uv).values)
    assert "disabled" not in viewer.clear_btn.state()
    # The map keeps its own extent: the line doesn't stretch it.
    assert viewer._line_artist is not None

    # The same line on the next laser.
    viewer.show_laser(2)
    np.testing.assert_array_equal(
        viewer.profile.values,
        viewtools.profile(run.maps[2].values, run.grid,
                          *viewer.line_uv).values)

    # A click is not a line: the one drawn stays.
    _mouse(viewer, "button_press_event", 0.1, 0.1)
    _mouse(viewer, "button_release_event", 0.1, 0.1)
    assert np.ravel(viewer.line_uv) == pytest.approx([u0, v0, u1, v1], abs=1e-3)

    viewer.clear_profile()
    assert viewer.line_uv is None and viewer.profile is None
    assert "disabled" in viewer.clear_btn.state()


def test_reload_keeps_the_laser_and_the_line(viewer, run_folder):
    opened(viewer, run_folder)
    viewer.show_laser(2)
    viewer.draw_profile((0.02, 0.05), (0.2, 0.1))
    viewer.reload()
    wait_loaded(viewer)
    assert viewer.laser == 2
    assert viewer.line_uv == ((0.02, 0.05), (0.2, 0.1))
    assert viewer.profile is not None


def test_a_folder_without_maps_says_so(viewer, run_folder, tmp_path,
                                       monkeypatch):
    shown = []
    monkeypatch.setattr("multilbic.gui.viewer.messagebox.showerror",
                        lambda title, text, **kw: shown.append(text))
    viewer.load(tmp_path)
    wait_loaded(viewer)
    assert viewer.run is None
    assert shown and "no laser maps" in shown[0]
    assert "not opened" in viewer.status_label.cget("text")
    # The next folder opens as usual.
    folder = shutil.copytree(run_folder, tmp_path / "copy")
    assert opened(viewer, folder).lasers == [1, 2]


def test_the_viewer_matches_read_folder(run_folder):
    """The window draws what `read_folder` gives: nothing of its own."""
    run = read_folder(run_folder)
    assert run.grid.shape == run.maps[1].values.shape
