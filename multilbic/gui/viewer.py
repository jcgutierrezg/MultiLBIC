"""
The viewer: a run's maps, read from its folder (D30).

    multilbic view [FOLDER]

    header:  name, version, the run ........................ Light/Dark
    body:    run and lasers | the map | colour, cursor, profile
    footer:  the last thing that happened

Its own window, on the PC and on the Pi: it reads run folders and
nothing else, so it needs no device and takes no lock, and it can stay
open beside `multilbic gui` while a run is going (Reload reads the rows
written since).

**The map** is drawn as the machine window draws it (`store/image.
draw_map`, turned to `[display]`), on white paper in both modes, with
matplotlib's toolbar to zoom and pan. Its unit follows its size (`viewtools.
display_unit`). **Colour limits**: auto (all but the extreme percent at
either end), full (smallest to largest), or typed. **The cursor**: where
it is on the sample, and the value there. **A line profile**: drag on the
map (with the toolbar's zoom and pan off); the line stays where it is
when another laser is picked, so the same line can be read at every
wavelength. Keys 1-6 pick a laser.

Folders are read on a thread (a big run takes seconds); only the Tk
thread touches a widget (SMUniversal rule 8).
"""

from __future__ import annotations

import datetime
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING, Any

import numpy as np
from matplotlib.backends.backend_tkagg import (
    FigureCanvasTkAgg,
    NavigationToolbar2Tk,
)
from matplotlib.figure import Figure
from smuniversal_lab_suite.core.gui.theme import Theme, set_dark_title_bar

from multilbic.config.machine import MachineConfig
from multilbic.gui import look, viewtools
from multilbic.gui.spectrum import wavelength_colour
from multilbic.run.session import REAL_RUNS, SIM_RUNS
from multilbic.store.image import draw_map, shift_note
from multilbic.store.runfolder import RunFolder, RunFolderError, read_folder
from multilbic.version import app_version

if TYPE_CHECKING:
    from matplotlib.backend_bases import MouseEvent
    from matplotlib.colorbar import Colorbar
    from matplotlib.image import AxesImage
    from matplotlib.lines import Line2D

POLL_MS = 50
LEFT_COLUMN_PX = 300
RIGHT_COLUMN_PX = 400
#: The profile's line on the map.
LINE_COLOUR = "cyan"
#: A press and release closer than this (in pixels on the screen) is a
#: click, not a line.
MIN_DRAG_PX = 4


class Viewer:
    def __init__(
        self,
        root: tk.Tk | tk.Toplevel,
        machine: MachineConfig,
        *,
        theme: Theme | None = None,
        folder: str | Path | None = None,
    ):
        self.root = root
        self.machine = machine
        self.view = machine.display.view
        self.theme = theme or look.make_theme(root)
        self.run: RunFolder | None = None
        self.laser: int | None = None
        self.loading = False
        self._results: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._poll_id: str | None = None
        #: The colour limits: "auto", "full" or "set" (`limits_a`).
        self.limits_mode = tk.StringVar(value="auto")
        self.limits_a: tuple[float, float] | None = None
        self.unit: tuple[str, float] = ("nA", 1e-9)
        self.image: AxesImage | None = None
        self.colorbar: Colorbar | None = None
        #: The profile's ends on the sample (u, v), once one is drawn.
        self.line_uv: tuple[tuple[float, float], tuple[float, float]] | None \
            = None
        self.profile: viewtools.Profile | None = None
        self._line_artist: Line2D | None = None
        self._drag_start: tuple[float, float, float, float] | None = None

        root.title("MultiLBIC viewer")
        root.minsize(1100, 680)
        root.bind("<Destroy>", self._destroyed, add="+")
        root.bind("<Key>", self._key, add="+")

        self._build_header()
        body = ttk.Frame(root, padding=(10, 8))
        body.grid(row=1, column=0, sticky="nsew")
        root.rowconfigure(1, weight=1)
        root.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, minsize=LEFT_COLUMN_PX)
        body.columnconfigure(1, weight=1)
        body.columnconfigure(2, minsize=RIGHT_COLUMN_PX)
        self._build_left(body)
        self._build_map(body)
        self._build_right(body)

        footer = ttk.Frame(root, padding=(10, 2, 10, 6))
        footer.grid(row=2, column=0, sticky="ew")
        self.status_label = ttk.Label(footer, text="", style="Hint.TLabel")
        self.status_label.pack(side="left")

        # Called at once, and again on every change of mode.
        self.theme.on_change(self._repaint)
        self._show_nothing()
        if folder is not None:
            self.load(folder)

    # ---- layout ----

    def _build_header(self) -> None:
        outer = ttk.Frame(self.root, style="Header.TFrame")
        outer.grid(row=0, column=0, sticky="ew")
        outer.columnconfigure(1, weight=1)
        self.header_bar = ttk.Frame(outer, style="AccentBar.TFrame")
        header = ttk.Frame(outer, style="Header.TFrame", padding=(10, 6))
        header.grid(row=0, column=1, sticky="ew")
        self.emblem = tk.Canvas(header, width=look.EMBLEM_SIZE,
                                height=look.EMBLEM_SIZE,
                                highlightthickness=0, borderwidth=0)
        self.emblem.pack(side="left", padx=(0, 10))
        names = ttk.Frame(header, style="Header.TFrame")
        names.pack(side="left")
        top = ttk.Frame(names, style="Header.TFrame")
        top.pack(anchor="w")
        ttk.Label(top, text="MultiLBIC viewer",
                  style="Title.Header.TLabel").pack(side="left")
        ttk.Label(top, text=app_version(),
                  style="Sub.Header.TLabel").pack(side="left", padx=(8, 0))
        ttk.Label(names, text="a run's maps, from its folder",
                  style="Sub.Header.TLabel").pack(anchor="w")
        self.run_label = ttk.Label(header, text="", style="Header.TLabel")
        self.run_label.pack(side="left", padx=(24, 0))
        self.mode_btn = ttk.Button(header, style="Header.TButton", width=6,
                                   command=self.theme.toggle)
        self.mode_btn.pack(side="right")

    def _build_left(self, body: ttk.Frame) -> None:
        column = ttk.Frame(body)
        column.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        run = look.section(column, "Run")
        run.pack(fill="x", pady=(0, 8))
        buttons = ttk.Frame(run)
        buttons.pack(fill="x", pady=(0, 6))
        self.open_btn = ttk.Button(buttons, text="Open folder...",
                                   style="Run.TButton",
                                   command=self.ask_folder)
        self.open_btn.pack(side="left")
        self.reload_btn = ttk.Button(buttons, text="Reload",
                                     command=self.reload)
        self.reload_btn.pack(side="left", padx=(6, 0))
        self.run_info = ttk.Label(run, text="", justify="left",
                                  wraplength=LEFT_COLUMN_PX - 30)
        self.run_info.pack(anchor="w", fill="x")
        self.lasers_frame = look.section(column, "Lasers")
        self.lasers_frame.pack(fill="x", pady=(0, 8))
        self.laser_var = tk.IntVar(value=0)
        self.laser_buttons: dict[int, ttk.Radiobutton] = {}
        self.files_note = ttk.Label(column, text="", style="Hint.TLabel",
                                    justify="left",
                                    wraplength=LEFT_COLUMN_PX - 10)
        self.files_note.pack(anchor="w", fill="x")

    def _build_map(self, body: ttk.Frame) -> None:
        frame = look.section(body, "Map")
        frame.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
        # Maps are on white paper in both modes, as in the machine window.
        # Small to start with: the canvas grows into the window, and never
        # pushes it past the screen.
        self.figure = Figure(figsize=(4, 3), dpi=100, facecolor="white")
        self.axes = self.figure.add_subplot()
        self.canvas = FigureCanvasTkAgg(self.figure, master=frame)
        self.toolbar = NavigationToolbar2Tk(self.canvas, frame,
                                            pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(side="bottom", fill="x")
        self.caption = ttk.Label(frame, text="", style="Hint.TLabel",
                                 justify="left")
        self.caption.pack(side="bottom", anchor="w", pady=(4, 2))
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas.mpl_connect("motion_notify_event", self._motion)
        self.canvas.mpl_connect("button_press_event", self._press)
        self.canvas.mpl_connect("button_release_event", self._release)

    def _build_right(self, body: ttk.Frame) -> None:
        column = ttk.Frame(body, width=RIGHT_COLUMN_PX)
        column.grid(row=0, column=2, sticky="nsew")
        colour = look.section(column, "Colour")
        colour.pack(fill="x", pady=(0, 8))
        modes = ttk.Frame(colour)
        modes.pack(fill="x")
        for value, text in (("auto", "Auto (1-99 %)"), ("full", "Full"),
                            ("set", "Set")):
            ttk.Radiobutton(modes, text=text, value=value,
                            variable=self.limits_mode,
                            command=self._mode_changed) \
                .pack(side="left", padx=(0, 10))
        typed = ttk.Frame(colour)
        typed.pack(fill="x", pady=(6, 0))
        self.lo_var = tk.StringVar()
        self.hi_var = tk.StringVar()
        ttk.Label(typed, text="from").pack(side="left")
        self.lo_entry = ttk.Entry(typed, textvariable=self.lo_var, width=10)
        self.lo_entry.pack(side="left", padx=(4, 6))
        ttk.Label(typed, text="to").pack(side="left")
        self.hi_entry = ttk.Entry(typed, textvariable=self.hi_var, width=10)
        self.hi_entry.pack(side="left", padx=(4, 6))
        self.unit_label = ttk.Label(typed, text="")
        self.unit_label.pack(side="left")
        self.apply_btn = ttk.Button(typed, text="Apply",
                                    command=self.apply_typed)
        self.apply_btn.pack(side="right")
        for entry in (self.lo_entry, self.hi_entry):
            entry.bind("<Return>", lambda e: self.apply_typed())

        cursor = look.section(column, "Cursor")
        cursor.pack(fill="x", pady=(0, 8))
        self.readout = ttk.Label(cursor, text="-", justify="left")
        self.readout.pack(anchor="w")

        prof = look.section(column, "Profile")
        prof.pack(fill="both", expand=True)
        top = ttk.Frame(prof)
        top.pack(fill="x")
        self.profile_note = ttk.Label(
            top, text="Drag across the map to draw a line.",
            style="Hint.TLabel", justify="left",
            wraplength=RIGHT_COLUMN_PX - 110)
        self.profile_note.pack(side="left", anchor="w")
        self.clear_btn = ttk.Button(top, text="Clear",
                                    command=self.clear_profile)
        self.clear_btn.pack(side="right")
        self.profile_figure = Figure(figsize=(3.6, 2.4), dpi=100,
                                     facecolor="white")
        self.profile_axes = self.profile_figure.add_subplot()
        self.profile_canvas = FigureCanvasTkAgg(self.profile_figure,
                                                master=prof)
        self.profile_canvas.get_tk_widget().pack(fill="both", expand=True,
                                                 pady=(6, 0))

    def _repaint(self, theme: Theme) -> None:
        self.root.configure(background=theme.palette.bg)
        set_dark_title_bar(self.root, theme.is_dark)
        self.mode_btn.configure(text="Light" if theme.is_dark else "Dark")
        look.draw_emblem(self.emblem, theme, [
            (laser.number, wavelength_colour(laser.wavelength_nm))
            for laser in self.machine.lasers])
        bar = self.header_bar
        bar.grid_forget()
        if theme.is_dark:
            bar.configure(width=5)
            bar.grid(row=0, column=0, sticky="ns")
        else:
            bar.configure(height=3)
            bar.grid(row=1, column=0, columnspan=2, sticky="ew")

    # ---- opening a folder ----

    def ask_folder(self) -> None:
        folder = filedialog.askdirectory(
            parent=self.root, title="A run folder",
            initialdir=str(self._start_dir()), mustexist=True)
        if folder:
            self.load(folder)

    def _start_dir(self) -> Path:
        if self.run is not None:
            return self.run.path.parent
        for candidate in (REAL_RUNS, SIM_RUNS.resolve()):
            if candidate.is_dir():
                return candidate
        return Path.home()

    def reload(self) -> None:
        """Read the open folder again: a run still going has more rows."""
        if self.run is not None:
            self.load(self.run.path)

    def load(self, folder: str | Path) -> None:
        """Read `folder` on a thread; the window shows it when done."""
        if self.loading:
            return
        self.loading = True
        self._set_busy(True)
        self.status(f"reading {Path(folder).name}...")

        def work() -> None:
            def progress(done: int, total: int, path: Path) -> None:
                self._results.put(
                    ("progress", f"reading {path.name} ({done + 1} of "
                                 f"{total})"))
            try:
                run = read_folder(folder, on_file=progress)
            except (RunFolderError, OSError) as exc:
                self._results.put(("error", str(exc)))
            except Exception as exc:  # noqa: BLE001 - shown, not raised
                self._results.put(("error", f"{type(exc).__name__}: {exc}"))
            else:
                self._results.put(("done", run))

        threading.Thread(target=work, name="viewer-read", daemon=True).start()
        self._poll_id = self.root.after(POLL_MS, self._poll)

    def _poll(self) -> None:
        self._poll_id = None
        while True:
            try:
                kind, payload = self._results.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                self.status(payload)
            elif kind == "error":
                self._loaded(None, payload)
                return
            elif kind == "done":
                self._loaded(payload, None)
                return
        self._poll_id = self.root.after(POLL_MS, self._poll)

    def _loaded(self, run: RunFolder | None, error: str | None) -> None:
        self.loading = False
        if run is None:
            self._set_busy(False)
            self.status(f"not opened: {error}")
            messagebox.showerror("Not opened", str(error), parent=self.root)
            return
        same = self.run is not None and self.run.path == run.path
        self.run = run
        self._set_busy(False)
        self._fill_run()
        keep = self.laser if same and self.laser in run.maps else None
        if not same:
            self.line_uv = None
        self.show_laser(keep if keep is not None else run.lasers[0])
        self.status(f"opened {run.path}")

    def _set_busy(self, busy: bool) -> None:
        state = ["disabled"] if busy else ["!disabled"]
        self.open_btn.state(state)
        self.reload_btn.state(
            state if busy or self.run is not None else ["disabled"])

    def _fill_run(self) -> None:
        run = self.run
        assert run is not None
        self.run_label.configure(text=f"{run.sample or run.run_id}"
                                 + ("  (simulated)" if run.simulated else ""))
        lines = [run.run_id, f"sample: {run.sample or '-'}",
                 f"started: {_when(run.started)}", f"status: {run.status}"]
        if run.note:
            lines.append(f"note: {run.note}")
        g = run.grid
        u0, u1, v0, v1 = g.extent_mm
        lines.append(f"{u1 - u0:g} x {v1 - v0:g} mm, pixel "
                     f"{g.pixel_mm * 1000:g} um, rows {g.pitch_mm * 1000:g} um")
        self.run_info.configure(text="\n".join(lines))

        for button in self.laser_buttons.values():
            button.destroy()
        self.laser_buttons = {}
        for n, m in run.maps.items():
            text = f" {n}: {m.wavelength_nm:g} nm"
            if not m.complete:
                text += f" ({m.status})"
            button = ttk.Radiobutton(
                self.lasers_frame, text=text, value=n,
                variable=self.laser_var, compound="left",
                image=look.swatch(self.lasers_frame,
                                  wavelength_colour(m.wavelength_nm)),
                command=lambda n=n: self.show_laser(n))
            button.pack(anchor="w", pady=1)
            self.laser_buttons[n] = button

        notes = []
        if run.attempts:
            notes.append("Clipped attempts (not shown): " + ", ".join(
                a.path.name for a in run.attempts))
        if run.problems:
            notes.append("Not read: " + "; ".join(
                f"{name} ({why})" for name, why in run.problems.items()))
        self.files_note.configure(text="\n".join(notes))

    # ---- the map ----

    def _show_nothing(self) -> None:
        self.axes.clear()
        self.axes.set_axis_off()
        self.axes.text(0.5, 0.5, "Open a run folder", ha="center",
                       va="center", transform=self.axes.transAxes,
                       color="#666666", fontsize=12)
        self.canvas.draw_idle()
        self.reload_btn.state(["disabled"])
        self.clear_btn.state(["disabled"])

    def show_laser(self, laser: int) -> None:
        run = self.run
        if run is None or laser not in run.maps:
            return
        self.laser = laser
        self.laser_var.set(laser)
        m = run.maps[laser]
        self.unit = viewtools.display_unit(m.values)
        if self.colorbar is not None:
            self.colorbar.remove()
            self.colorbar = None
        self.axes.clear()
        self.axes.set_axis_on()
        u0, u1, v0, v1 = run.grid.extent_mm
        self.image = draw_map(self.axes, m.values, u1 - u0, v1 - v0,
                              self.view, per_unit_a=self.unit[1])
        self.colorbar = self.figure.colorbar(
            self.image, ax=self.axes, label=f"photocurrent ({self.unit[0]})")
        self.axes.set_title(m.label(), fontsize=10)
        self.unit_label.configure(text=self.unit[0])
        self._line_artist = None
        self.figure.tight_layout()
        self._apply_limits()
        bits = [m.status, shift_note(m.result),
                f"baseline {look.amps(m.result.baseline.offset_a)} "
                f"subtracted, noise {look.amps(m.noise_a)}"]
        if m.current_range_a is not None:
            bits.append(f"range {look.amps(m.current_range_a)}")
        self.caption.configure(text=", ".join(bits))
        if self.line_uv is not None:
            self._set_line(*self.line_uv)
        self.canvas.draw_idle()

    def values(self) -> np.ndarray | None:
        """The shown laser's map, A, on the run's grid."""
        if self.run is None or self.laser is None:
            return None
        return self.run.maps[self.laser].values

    # ---- colour limits ----

    def _mode_changed(self) -> None:
        if self.limits_mode.get() == "set":
            self.apply_typed()
        else:
            self._apply_limits()

    def apply_typed(self) -> None:
        """The typed limits, in the map's unit."""
        try:
            lo = float(self.lo_var.get()) * self.unit[1]
            hi = float(self.hi_var.get()) * self.unit[1]
        except ValueError:
            self.status("colour limits: two numbers")
            return
        if not hi > lo:
            self.status("colour limits: the second must be above the first")
            return
        self.limits_a = (lo, hi)
        self.limits_mode.set("set")
        self._apply_limits()

    def _apply_limits(self) -> None:
        values = self.values()
        if values is None or self.image is None:
            return
        mode = self.limits_mode.get()
        if mode == "set" and self.limits_a is not None:
            limits: tuple[float, float] | None = self.limits_a
        elif mode == "full":
            limits = viewtools.full_limits(values)
        else:
            limits = viewtools.auto_limits(values)
        if limits is None:
            return
        scale = self.unit[1]
        lo, hi = limits[0] / scale, limits[1] / scale
        self.image.set_clim(lo, hi)
        self.lo_var.set(f"{lo:.4g}")
        self.hi_var.set(f"{hi:.4g}")
        self.canvas.draw_idle()

    def clim(self) -> tuple[float, float] | None:
        """The colour limits drawn now, in the map's unit."""
        return None if self.image is None else self.image.get_clim()

    # ---- the cursor and the profile ----

    def _tools_idle(self) -> bool:
        """Neither zoom nor pan is on in the toolbar."""
        return not str(getattr(self.toolbar, "mode", ""))

    def _motion(self, event: MouseEvent) -> None:
        if event.inaxes is not self.axes or event.xdata is None \
                or event.ydata is None:
            return
        self.show_cursor(*viewtools.to_uv(self.view, event.xdata,
                                          event.ydata))
        if self._drag_start is not None:
            u0, v0 = self._drag_start[:2]
            self._set_line((u0, v0), viewtools.to_uv(
                self.view, event.xdata, event.ydata), compute=False)
            self.canvas.draw_idle()

    def show_cursor(self, u: float, v: float) -> None:
        values = self.values()
        if values is None or self.run is None:
            return
        value = viewtools.value_at(values, self.run.grid, u, v)
        where = f"u {u:.3f} mm, v {v:.3f} mm"
        if value is None:
            self.readout.configure(text=f"{where}\noff the map")
            return
        # An empty pixel is filled in the picture from its neighbours
        # (`store/image.fill_short_gaps`), never in the data.
        shown = (look.amps(value) if np.isfinite(value)
                 else "no samples in this pixel")
        self.readout.configure(text=f"{where}\n{shown}  (laser {self.laser})")

    def _press(self, event: MouseEvent) -> None:
        if (event.button != 1 or event.inaxes is not self.axes
                or event.xdata is None or event.ydata is None
                or not self._tools_idle() or self.values() is None):
            return
        u, v = viewtools.to_uv(self.view, event.xdata, event.ydata)
        self._drag_start = (u, v, float(event.x), float(event.y))

    def _release(self, event: MouseEvent) -> None:
        start, self._drag_start = self._drag_start, None
        if start is None:
            return
        if event.xdata is None or event.ydata is None \
                or event.inaxes is not self.axes:
            if self.line_uv is not None:
                self._set_line(*self.line_uv)
            self.canvas.draw_idle()
            return
        moved = abs(event.x - start[2]) + abs(event.y - start[3])
        if moved < MIN_DRAG_PX:
            # A click: the line, if any, stays as it was.
            if self.line_uv is not None:
                self._set_line(*self.line_uv)
            else:
                self._remove_line()
            self.canvas.draw_idle()
            return
        self.draw_profile((start[0], start[1]), viewtools.to_uv(
            self.view, event.xdata, event.ydata))

    def draw_profile(self, start_uv: tuple[float, float],
                     end_uv: tuple[float, float]) -> None:
        """A line from `start_uv` to `end_uv` on the sample, and the map
        along it."""
        self.line_uv = (start_uv, end_uv)
        self._set_line(start_uv, end_uv)
        self.canvas.draw_idle()

    def _set_line(self, start_uv: tuple[float, float],
                  end_uv: tuple[float, float], *, compute: bool = True) -> None:
        x0, y0 = viewtools.to_xy(self.view, *start_uv)
        x1, y1 = viewtools.to_xy(self.view, *end_uv)
        if self._line_artist is None:
            # The map's extent stays: a line past its edge is clipped,
            # not given room.
            (self._line_artist,) = self.axes.plot(
                [x0, x1], [y0, y1], color=LINE_COLOUR, lw=1.5,
                marker="o", markersize=4, scalex=False, scaley=False)
        else:
            self._line_artist.set_data([x0, x1], [y0, y1])
        if compute:
            self._plot_profile(start_uv, end_uv)

    def _remove_line(self) -> None:
        if self._line_artist is not None:
            self._line_artist.remove()
            self._line_artist = None

    def _plot_profile(self, start_uv: tuple[float, float],
                      end_uv: tuple[float, float]) -> None:
        values = self.values()
        if values is None or self.run is None:
            return
        self.profile = viewtools.profile(values, self.run.grid, start_uv,
                                         end_uv)
        p = self.profile
        name, scale = self.unit
        ax = self.profile_axes
        ax.clear()
        m = self.run.maps[self.laser] if self.laser is not None else None
        ax.plot(p.distance_mm, p.values / scale, lw=1.2,
                color=wavelength_colour(m.wavelength_nm) if m else None)
        ax.set_xlabel("distance along the line (mm)")
        ax.set_ylabel(f"photocurrent ({name})")
        if m is not None:
            ax.set_title(m.label(), fontsize=9)
        ax.grid(True, alpha=0.3)
        self.profile_figure.tight_layout()
        self.profile_canvas.draw_idle()
        (u0, v0), (u1, v1) = start_uv, end_uv
        self.profile_note.configure(
            text=f"({u0:.3f}, {v0:.3f}) to ({u1:.3f}, {v1:.3f}) mm, "
                 f"{p.length_mm:.3f} mm long")
        self.clear_btn.state(["!disabled"])

    def clear_profile(self) -> None:
        self.line_uv = None
        self.profile = None
        self._remove_line()
        self.profile_axes.clear()
        self.profile_canvas.draw_idle()
        self.profile_note.configure(text="Drag across the map to draw a line.")
        self.clear_btn.state(["disabled"])
        self.canvas.draw_idle()

    # ---- keys, status, closing ----

    def _key(self, event: tk.Event) -> None:
        if isinstance(event.widget, (tk.Entry, ttk.Entry)):
            return
        if event.char and event.char.isdigit() and self.run is not None:
            self.show_laser(int(event.char))

    def status(self, text: str) -> None:
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.status_label.configure(text=f"{stamp}  {text}")

    def _destroyed(self, event: tk.Event) -> None:
        if event.widget is self.root and self._poll_id is not None:
            try:
                self.root.after_cancel(self._poll_id)
            except tk.TclError:
                pass
            self._poll_id = None


def _when(iso: str) -> str:
    """'2026-11-06 14:54 UTC' from the header's ISO time."""
    if not iso:
        return "-"
    try:
        t = datetime.datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return t.strftime("%Y-%m-%d %H:%M") + (" UTC" if t.tzinfo else "")


def launch_viewer(machine: MachineConfig, folder: str | None = None) -> int:
    """Open the viewer, on `folder` if given, until it is closed."""
    from smuniversal_lab_suite.core.gui.maximize import maximize

    root = tk.Tk()
    Viewer(root, machine, folder=folder)
    maximize(root)
    root.mainloop()
    return 0
