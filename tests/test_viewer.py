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


def test_a_ratio_is_blank_where_the_laser_below_gives_little():
    top = np.array([[-2.0, -1.0, -0.5, np.nan]])
    bottom = np.array([[-1.0, -1.0, -0.01, -1.0]])
    r = viewtools.ratio(top, bottom)
    np.testing.assert_allclose(r[0, :2], [2.0, 1.0])
    # Under 5 % of the bottom laser's top value, and empty pixels: blank.
    assert np.isnan(r[0, 2]) and np.isnan(r[0, 3])
    assert np.isnan(viewtools.ratio(top, np.full((1, 4), np.nan))).all()


@pytest.mark.parametrize("n, area, shape, grid", [
    (1, 1.6, 1.0, (1, 1)),
    (3, 1.1, 0.9, (2, 2)),   # a squarish area: two rows are bigger
    (3, 2.5, 1.0, (1, 3)),   # a wide area: one row
    (6, 1.6, 1.0, (2, 3)),
    (2, 1.1, 4.0, (2, 1)),   # long thin maps stack
])
def test_panels_are_laid_out_as_big_as_they_fit(n, area, shape, grid):
    assert viewtools.panel_grid(n, area, shape) == grid


def test_one_colour_scale_over_several_maps():
    a, b = np.array([0.0, 1.0]), np.array([5.0, np.nan])
    assert viewtools.shared_limits([a, b], "full") == (0.0, 5.0)
    assert viewtools.shared_limits([np.array([np.nan])], "auto") is None


def test_an_area_takes_the_pixels_inside_it():
    mask = viewtools.area_mask(GRID, (0.02, 0.05), (0.05, 0.15))
    # Columns centred at 0.025, 0.035, 0.045; rows at 0.075, 0.125.
    assert mask.sum() == 6
    assert mask[1:3, 2:5].all()
    # A click: the one pixel under it, whichever way it was dragged.
    one = viewtools.area_mask(GRID, (0.031, 0.06), (0.031, 0.06))
    assert one.sum() == 1 and one[1, 3]
    assert (viewtools.area_mask(GRID, (0.05, 0.15), (0.02, 0.05))
            == mask).all()


def test_the_spectrum_over_an_area():
    values = np.arange(40.0).reshape(4, 10)
    mask = viewtools.area_mask(GRID, (0.0, 0.0), (0.1, 0.2))
    empty = np.full((4, 10), np.nan)
    points = viewtools.spectrum(
        {6: (848.0, values * 2), 1: (444.0, values), 2: (519.0, empty)},
        mask)
    # In wavelength order; a laser with nothing there left out.
    assert [p.laser for p in points] == [1, 6]
    first = points[0]
    assert first.median == pytest.approx(np.median(values))
    assert first.low == pytest.approx(np.percentile(values, 16))
    assert first.high == pytest.approx(np.percentile(values, 84))
    assert first.pixels == 40


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


def _mouse(viewer, name, u, v, button=1, axes=None):
    """A matplotlib mouse event at u, v on the drawn map (on `axes`, or
    the current panel's)."""
    from matplotlib.backend_bases import MouseEvent

    x, y = viewtools.to_xy(viewer.view, u, v)
    px, py = (axes or viewer.axes).transData.transform((x, y))
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
    assert all(p.line is not None for p in viewer.panels)

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


def test_the_alignment_can_be_set_by_hand_and_searched_again(
        viewer, run_folder, tmp_path):
    from multilbic.store import alignfile

    folder = shutil.copytree(run_folder, tmp_path / run_folder.name)
    run = opened(viewer, folder)
    assert all(m.reused for m in run.maps.values())  # saved by the run
    assert "2 of 2 from saved alignments" in viewer.status_label.cget("text")
    assert "computed by the run" in viewer.align_note.cget("text")
    viewer.show_laser(2)
    viewer.draw_profile((0.02, 0.075), (0.28, 0.075))
    searched = run.maps[2].result.alignment.shift_mm * 1000

    viewer.shift_var.set("41.5")
    viewer.set_shift()
    wait_loaded(viewer)
    m = viewer.run.maps[2]
    assert m.result.alignment.shift_mm == pytest.approx(0.0415)
    assert "by hand" in viewer.align_note.cget("text")
    assert "shift 41.5 µm" in viewer.status_label.cget("text")
    assert alignfile.load(m.path).by_hand
    # Laser 2 is still shown, its line and profile with it, now from
    # the new map.
    assert viewer.laser == 2 and viewer.line_uv is not None
    np.testing.assert_array_equal(
        viewer.profile.values,
        viewtools.profile(m.values, viewer.run.grid, *viewer.line_uv).values)

    # Opened again, it keeps the shift set by hand.
    viewer.load(folder)
    wait_loaded(viewer)
    assert viewer.run.maps[2].saved.by_hand

    viewer.realign()
    wait_loaded(viewer)
    m = viewer.run.maps[2]
    assert not m.saved.by_hand
    assert m.result.alignment.shift_mm * 1000 == pytest.approx(searched)
    assert "computed by the viewer" in viewer.align_note.cget("text")

    viewer.shift_var.set("lots")
    viewer.set_shift()  # not a number: refused, nothing rebuilt
    assert not viewer.loading
    assert "number" in viewer.status_label.cget("text")


def test_side_by_side_one_scale_or_each_its_own(viewer, run_folder):
    run = opened(viewer, run_folder)
    viewer.show_side_by_side(shared=True)
    assert [p.laser for p in viewer.panels] == [1, 2]
    scale = viewer.unit[1]
    assert viewer.unit == viewtools.display_unit(run.stack())
    together = viewtools.shared_limits(
        [run.maps[1].values, run.maps[2].values], "auto")
    for p in viewer.panels:
        assert p.image.get_clim() == pytest.approx(
            (together[0] / scale, together[1] / scale))
    assert "one colour scale" in viewer.caption.cget("text")

    viewer.show_side_by_side(shared=False)
    for p in viewer.panels:
        own = viewtools.auto_limits(run.maps[p.laser].values)
        assert p.image.get_clim() == pytest.approx(
            (own[0] / scale, own[1] / scale))

    # The cursor reads both, the profile is each laser's.
    viewer.canvas.draw()
    viewer.show_cursor(0.105, 0.075)
    text = viewer.readout.cget("text")
    assert "laser 1:" in text and "laser 2:" in text
    viewer.draw_profile((0.02, 0.075), (0.28, 0.075))
    assert sorted(viewer.profiles) == [1, 2]
    assert all(p.line is not None for p in viewer.panels)
    np.testing.assert_array_equal(
        viewer.profiles[2].values,
        viewtools.profile(run.maps[2].values, run.grid,
                          *viewer.line_uv).values)

    # A click on laser 2's map makes it the current laser.
    second = viewer.panels[1].axes
    _mouse(viewer, "button_press_event", 0.1, 0.1, axes=second)
    _mouse(viewer, "button_release_event", 0.1, 0.1, axes=second)
    assert viewer.laser == 2 and viewer.view_mode.get() == "side"
    assert viewer.line_uv is not None  # a click keeps the line

    # Picking a laser from the list shows it alone.
    viewer.show_laser(1)
    assert viewer.view_mode.get() == "one" and len(viewer.panels) == 1


def test_the_ratio_of_two_lasers(viewer, run_folder):
    run = opened(viewer, run_folder)
    viewer.show_ratio(2, 1)
    assert len(viewer.panels) == 1 and viewer.panels[0].laser is None
    expected = viewtools.ratio(run.maps[2].values, run.maps[1].values)
    np.testing.assert_array_equal(viewer.values(), expected)
    assert viewer.unit == ("", 1.0)
    assert viewer.unit_label.cget("text") == "ratio"
    assert "over laser 1" in viewer.caption.cget("text")
    assert viewer.ratio_top.get().startswith("2:")
    assert viewer.ratio_bottom.get().startswith("1:")

    viewer.show_cursor(0.105, 0.075)
    assert "ratio:" in viewer.readout.cget("text")
    viewer.draw_profile((0.02, 0.075), (0.28, 0.075))
    np.testing.assert_array_equal(
        viewer.profile.values,
        viewtools.profile(expected, run.grid, *viewer.line_uv).values)

    # Swapped from the boxes, as a person would.
    viewer.ratio_top.set(viewer.ratio_top_box.cget("values")[0])
    viewer.ratio_bottom.set(viewer.ratio_bottom_box.cget("values")[1])
    viewer.ratio_top_box.event_generate("<<ComboboxSelected>>")
    viewer.root.update()
    assert viewer.ratio_pair == (1, 2)
    np.testing.assert_array_equal(
        viewer.values(),
        viewtools.ratio(run.maps[1].values, run.maps[2].values))

    # Reload keeps the view.
    viewer.reload()
    wait_loaded(viewer)
    assert viewer.view_mode.get() == "ratio" and viewer.ratio_pair == (1, 2)


def _with_power(folder, lasers, before=-1.0e-3, after=-1.1e-3):
    """Power readings added to these lasers' files, bracketing their
    rows, as a run since 0.7.6 writes them (a later key over an earlier
    one, so appending is enough)."""
    import json

    from multilbic.store.runfile import read_run

    for n in lasers:
        path = next(folder.glob(f"laser{n}_*nm.csv"))
        anchors = read_run(path).anchors
        t0, t1 = anchors[0].sent_s - 1.0, anchors[-1].end_s + 1.0
        entries = {
            "power_before": {"current_a": before, "t_s": t0},
            "power_after": {"current_a": after, "t_s": t1},
            "power_dark": {"current_a": 0.0, "t_s": t1 + 1.0},
        }
        with path.open("a", encoding="utf-8") as f:
            for key, value in entries.items():
                f.write(f"# {key}: {json.dumps(value)}\n")


def test_maps_shown_as_eqe(viewer, run_folder, tmp_path):
    folder = shutil.copytree(run_folder, tmp_path / run_folder.name)
    _with_power(folder, [1])
    run = opened(viewer, folder)
    m1, m2 = run.maps[1], run.maps[2]
    assert m1.eqe is not None and m1.power.drift == pytest.approx(0.1)
    assert m2.eqe is None and "no power readings" in m2.no_eqe

    viewer.show_laser(1)
    viewer.quantity.set("eqe")
    viewer.redraw()
    assert viewer.unit == ("%", 0.01)
    np.testing.assert_array_equal(viewer.values(), m1.eqe)
    assert "datasheet" in viewer.caption.cget("text")
    assert "+10.0%" in viewer.caption.cget("text")
    viewer.show_cursor(0.105, 0.075)
    assert "EQE" in viewer.readout.cget("text")
    viewer.draw_profile((0.02, 0.075), (0.28, 0.075))
    assert viewer.profile_axes.get_ylabel() == "EQE (%)"

    # Laser 2 has no power readings: its panel says so, blank.
    viewer.show_side_by_side()
    titles = [p.axes.get_title() for p in viewer.panels]
    assert titles[1].endswith("no EQE")
    assert np.isnan(viewer.panels[1].values).all()
    viewer.show_cursor(0.105, 0.075)
    assert "laser 2: no EQE" in viewer.readout.cget("text")

    # Back to photocurrent: the maps as they were.
    viewer.show_laser(1)
    viewer.quantity.set("current")
    viewer.redraw()
    np.testing.assert_array_equal(viewer.values(), m1.values)


def test_a_pixel_and_an_area_give_each_lasers_spectrum(viewer, run_folder,
                                                       tmp_path):
    folder = shutil.copytree(run_folder, tmp_path / run_folder.name)
    _with_power(folder, [1])
    run = opened(viewer, folder)
    viewer.draw_profile((0.02, 0.075), (0.28, 0.075))
    viewer.pick_mode.set("area")
    viewer._pick_mode_changed()
    assert "Click a pixel" in viewer.profile_note.cget("text")
    viewer.canvas.draw()

    # A click picks the pixel under it: each laser's value there.
    _mouse(viewer, "button_press_event", 0.105, 0.075)
    _mouse(viewer, "button_release_event", 0.105, 0.075)
    at = viewtools.pixel_at(run.grid, 0.105, 0.075)
    spectrum = {p.laser: p for p in viewer.spectrum}
    for n in (1, 2):
        value = run.maps[n].values[at]
        if np.isfinite(value):
            assert spectrum[n].median == pytest.approx(value)
            assert spectrum[n].pixels == 1
    assert "pixel at" in viewer.profile_note.cget("text")
    # The line drawn before is still there, its profile kept.
    assert viewer.line_uv is not None and viewer.profile is not None

    # A drag takes an area: the median over its pixels, every panel
    # showing the box.
    _mouse(viewer, "button_press_event", 0.03, 0.03)
    _mouse(viewer, "button_release_event", 0.2, 0.12)
    mask = viewtools.area_mask(run.grid, *viewer.area_uv)
    assert mask.sum() > 10  # 17 pixels of one row in the simulated map
    spectrum = {p.laser: p for p in viewer.spectrum}
    inside = run.maps[2].values[mask]
    assert spectrum[2].median == pytest.approx(
        np.median(inside[np.isfinite(inside)]))
    assert [p.wavelength_nm for p in viewer.spectrum] == sorted(
        p.wavelength_nm for p in viewer.spectrum)
    viewer.show_side_by_side()
    assert all(p.area is not None for p in viewer.panels)

    # As EQE: laser 1's, and laser 2 said to have none.
    viewer.quantity.set("eqe")
    viewer.redraw()
    assert [p.laser for p in viewer.spectrum] == [1]
    assert viewer.spectrum[0].median == pytest.approx(
        np.median(run.maps[1].eqe[mask][np.isfinite(run.maps[1].eqe[mask])]))
    assert "no EQE: laser 2" in viewer.profile_note.cget("text")
    assert viewer.profile_axes.get_xlabel() == "wavelength (nm)"

    # Back to the line: its profile shows again; Clear clears what the
    # mode draws.
    viewer.pick_mode.set("line")
    viewer._pick_mode_changed()
    assert viewer.profile_axes.get_xlabel() == "distance along the line (mm)"
    viewer.clear_current()
    assert viewer.line_uv is None and viewer.area_uv is not None
    viewer.pick_mode.set("area")
    viewer._pick_mode_changed()
    viewer.clear_current()
    assert viewer.area_uv is None and viewer.spectrum == []
    assert all(p.area is None for p in viewer.panels)
