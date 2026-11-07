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

**Comparing lasers** (above the map): **One laser**; **Side by side**,
every laser in a panel of its own, in one unit, with one colour scale or
each its own (a click on a panel makes that laser the current one, the
one the alignment section is about); **Ratio**, one laser over another
pixel by pixel, blank where the one below gives next to nothing
(`viewtools.ratio`). The cursor reads every laser shown, and the profile
plots each laser's along the same line in its colour, or the ratio.

Folders are read on a thread (a big run takes seconds); only the Tk
thread touches a widget (SMUniversal rule 8).
"""

from __future__ import annotations

import datetime
import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING, Any

import numpy as np
from matplotlib.backends.backend_tkagg import (
    FigureCanvasTkAgg,
    NavigationToolbar2Tk,
)
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from smuniversal_lab_suite.core.gui.theme import Theme, set_dark_title_bar

from multilbic.config.machine import MachineConfig
from multilbic.gui import look, viewtools
from multilbic.gui.spectrum import wavelength_colour
from multilbic.run.session import REAL_RUNS, SIM_RUNS
from multilbic.store.image import draw_map, shift_note
from multilbic.store.runfolder import (
    LaserMap,
    RunFolder,
    RunFolderError,
    read_folder,
    rebuild,
)
from multilbic.version import app_version

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.backend_bases import MouseEvent
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
#: EQE is shown in %: a fraction over this.
EQE_UNIT = ("%", 0.01)


@dataclass
class _Panel:
    """One map drawn in the map area: a laser's, or (laser None) the
    ratio."""

    laser: int | None
    axes: Axes
    image: AxesImage
    values: np.ndarray
    line: Line2D | None = None
    area: Rectangle | None = None


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
        #: "one", "side" or "ratio".
        self.view_mode = tk.StringVar(value="one")
        #: "current" or "eqe" (D32).
        self.quantity = tk.StringVar(value="current")
        self.shared_scale = tk.BooleanVar(value=True)
        self.ratio_pair: tuple[int, int] | None = None
        self.ratio_top = tk.StringVar()
        self.ratio_bottom = tk.StringVar()
        self.panels: list[_Panel] = []
        #: The current panel's axes and image.
        self.axes: Axes | None = None
        self.image: AxesImage | None = None
        #: The profile's ends on the sample (u, v), once one is drawn.
        self.line_uv: tuple[tuple[float, float], tuple[float, float]] | None \
            = None
        self.profile: viewtools.Profile | None = None
        #: Side by side: each laser's profile along the line.
        self.profiles: dict[int, viewtools.Profile] = {}
        #: What a drag draws: "line" (a profile) or "area" (a
        #: spectrum; a click picks one pixel).
        self.pick_mode = tk.StringVar(value="line")
        #: The area's corners on the sample (u, v), once one is drawn.
        self.area_uv: tuple[tuple[float, float], tuple[float, float]] \
            | None = None
        self.spectrum: list[viewtools.SpectrumPoint] = []
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
        views = ttk.Frame(frame)
        views.pack(side="top", fill="x", pady=(0, 6))
        for value, text in (("one", "One laser"), ("side", "Side by side"),
                            ("ratio", "Ratio")):
            ttk.Radiobutton(views, text=text, value=value,
                            variable=self.view_mode,
                            command=self._view_changed)                 .pack(side="left", padx=(0, 10))
        self.scale_box = ttk.Checkbutton(views, text="One colour scale",
                                         variable=self.shared_scale,
                                         command=self.redraw)
        self.scale_box.pack(side="left", padx=(6, 18))
        self.ratio_top_box = ttk.Combobox(views, textvariable=self.ratio_top,
                                          width=11, state="readonly")
        self.ratio_top_box.pack(side="left")
        ttk.Label(views, text=" / ").pack(side="left")
        self.ratio_bottom_box = ttk.Combobox(
            views, textvariable=self.ratio_bottom, width=11, state="readonly")
        self.ratio_bottom_box.pack(side="left")
        for box in (self.ratio_top_box, self.ratio_bottom_box):
            box.bind("<<ComboboxSelected>>", self._ratio_changed)
        shown = ttk.Frame(frame)
        shown.pack(side="top", fill="x", pady=(0, 6))
        ttk.Label(shown, text="Show").pack(side="left", padx=(0, 8))
        for value, text in (("current", "Photocurrent"), ("eqe", "EQE")):
            ttk.Radiobutton(shown, text=text, value=value,
                            variable=self.quantity, command=self.redraw)                 .pack(side="left", padx=(0, 10))
        # Maps are on white paper in both modes, as in the machine window.
        # Small to start with: the canvas grows into the window, and never
        # pushes it past the screen. Constrained layout keeps colour bars
        # and panels apart however many there are.
        self.figure = Figure(figsize=(4, 3), dpi=100, facecolor="white",
                             layout="constrained")
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

        # How the shown map was aligned (saved beside its file,
        # store/alignfile), and the two ways to change it.
        align = look.section(column, "Alignment")
        align.pack(fill="x", pady=(0, 8))
        self.align_note = ttk.Label(align, text="-", justify="left",
                                    wraplength=RIGHT_COLUMN_PX - 30)
        self.align_note.pack(anchor="w", fill="x")
        row = ttk.Frame(align)
        row.pack(fill="x", pady=(6, 0))
        self.realign_btn = ttk.Button(row, text="Re-align",
                                      command=self.realign)
        self.realign_btn.pack(side="left")
        ttk.Label(row, text="shift").pack(side="left", padx=(14, 4))
        self.shift_var = tk.StringVar()
        self.shift_entry = ttk.Entry(row, textvariable=self.shift_var,
                                     width=8)
        self.shift_entry.pack(side="left")
        ttk.Label(row, text="µm").pack(side="left", padx=(4, 6))
        self.set_shift_btn = ttk.Button(row, text="Set shift",
                                        command=self.set_shift)
        self.set_shift_btn.pack(side="right")
        self.shift_entry.bind("<Return>", lambda e: self.set_shift())

        prof = look.section(column, "Line or area")
        prof.pack(fill="both", expand=True)
        modes = ttk.Frame(prof)
        modes.pack(fill="x", pady=(0, 4))
        ttk.Label(modes, text="Drag draws").pack(side="left")
        for value, text in (("line", "a line: profile"),
                            ("area", "an area: spectrum")):
            ttk.Radiobutton(modes, text=text, value=value,
                            variable=self.pick_mode,
                            command=self._pick_mode_changed) \
                .pack(side="left", padx=(8, 0))
        top = ttk.Frame(prof)
        top.pack(fill="x")
        self.profile_note = ttk.Label(
            top, text="Drag across the map to draw a line.",
            style="Hint.TLabel", justify="left",
            wraplength=RIGHT_COLUMN_PX - 110)
        self.profile_note.pack(side="left", anchor="w")
        self.clear_btn = ttk.Button(top, text="Clear",
                                    command=self.clear_current)
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
                run = read_folder(folder, on_file=progress,
                                  machine=self.machine)
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
            elif kind == "rebuilt":
                self._rebuilt(*payload)
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
            self.area_uv = None
            self.ratio_pair = None
            self.view_mode.set("one")
        self._pick(keep if keep is not None else run.lasers[0])
        self._fill_ratio_boxes()
        self.redraw()
        reused = sum(m.reused for m in run.maps.values())
        self.status(f"opened {run.path} ({reused} of {len(run.maps)} "
                    "from saved alignments)")

    def _set_busy(self, busy: bool) -> None:
        self.loading = busy
        state = ["disabled"] if busy else ["!disabled"]
        self.open_btn.state(state)
        have = ["disabled"] if busy or self.run is None else ["!disabled"]
        for button in (self.reload_btn, self.realign_btn, self.set_shift_btn):
            button.state(have)

    # ---- the alignment ----

    def realign(self) -> None:
        """Search for the shown map's alignment again, with the code as
        it is now, and save it."""
        self._rebuild(realign=True)

    def set_shift(self) -> None:
        """The shown map's shift set by hand, in µm, and saved."""
        try:
            shift = float(self.shift_var.get())
        except ValueError:
            self.status("shift: a number of µm")
            return
        self._rebuild(shift_um=shift)

    def _rebuild(self, *, realign: bool = False,
                 shift_um: float | None = None) -> None:
        run, laser = self.run, self.laser
        if run is None or laser is None or self.loading:
            return
        before = run.maps[laser].saved
        self._set_busy(True)
        self.status(f"laser {laser}: "
                    + ("searching for the alignment again..." if realign
                       else f"building with a shift of {shift_um:g} µm..."))

        def work() -> None:
            try:
                new: LaserMap | str = rebuild(run, laser, realign=realign,
                                              shift_um=shift_um)
            except Exception as exc:  # noqa: BLE001 - shown, not raised
                new = f"{type(exc).__name__}: {exc}"
            self._results.put(("rebuilt", (laser, new, before)))

        threading.Thread(target=work, name="viewer-align",
                         daemon=True).start()
        self._poll_id = self.root.after(POLL_MS, self._poll)

    def _rebuilt(self, laser: int, new: LaserMap | str,
                 before: Any) -> None:
        self._set_busy(False)
        if isinstance(new, str):
            self.status(f"laser {laser}: not rebuilt: {new}")
            messagebox.showerror("Not rebuilt", new, parent=self.root)
            return
        was = (f"{before.alignment.shift_mm * 1000:.1f} µm"
               if before is not None and before.alignment.found else "none")
        now = (f"{new.result.alignment.shift_mm * 1000:.1f} µm"
               if new.result.alignment.found else "none")
        self.status(f"laser {laser}: shift {now} (was {was})"
                    + (f"; not saved: {new.not_saved}" if new.not_saved
                       else ", saved"))
        if laser == self.laser:
            self._show_alignment(new)
        self.redraw()

    def _show_alignment(self, m: LaserMap) -> None:
        a = m.result.alignment
        text = m.saved.describe() if m.saved is not None else "-"
        if m.not_saved:
            text += "\nnot saved beside the file: " + m.not_saved
        self.align_note.configure(text=text)
        self.shift_var.set(f"{a.shift_mm * 1000:.1f}" if a.found else "")

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
        self.figure.clear()
        self.panels = []
        ax = self.figure.add_subplot()
        ax.set_axis_off()
        ax.text(0.5, 0.5, "Open a run folder", ha="center", va="center",
                transform=ax.transAxes, color="#666666", fontsize=12)
        self.canvas.draw_idle()
        for button in (self.reload_btn, self.clear_btn, self.realign_btn,
                       self.set_shift_btn):
            button.state(["disabled"])

    def show_laser(self, laser: int) -> None:
        """Laser `laser` alone on the map."""
        if self.run is None or laser not in self.run.maps:
            return
        self._pick(laser)
        self.view_mode.set("one")
        self.redraw()

    def show_side_by_side(self, shared: bool | None = None) -> None:
        if shared is not None:
            self.shared_scale.set(shared)
        self.view_mode.set("side")
        self.redraw()

    def show_ratio(self, top: int, bottom: int) -> None:
        """Laser `top` over laser `bottom`, pixel by pixel."""
        self.ratio_pair = (top, bottom)
        self._fill_ratio_boxes()
        self.view_mode.set("ratio")
        self.redraw()

    def _pick(self, laser: int) -> None:
        """The current laser: the one the alignment section is about."""
        assert self.run is not None
        self.laser = laser
        self.laser_var.set(laser)
        self._show_alignment(self.run.maps[laser])

    def _view_changed(self) -> None:
        if self.view_mode.get() == "ratio":
            self._ratio_changed()
        else:
            self.redraw()

    def _ratio_changed(self, event: object = None) -> None:
        top = _laser_of(self.ratio_top.get())
        bottom = _laser_of(self.ratio_bottom.get())
        if top is not None and bottom is not None:
            self.ratio_pair = (top, bottom)
        self.view_mode.set("ratio")
        self.redraw()

    def _fill_ratio_boxes(self) -> None:
        run = self.run
        if run is None:
            return
        names = [_laser_name(n, m.wavelength_nm) for n, m in run.maps.items()]
        for box in (self.ratio_top_box, self.ratio_bottom_box):
            box.configure(values=names)
        if self.ratio_pair is None or not set(self.ratio_pair) <= set(run.maps):
            first = self.laser if self.laser in run.maps else run.lasers[0]
            others = [n for n in run.lasers if n != first]
            self.ratio_pair = (first, others[0] if others else first)
        top, bottom = self.ratio_pair
        self.ratio_top.set(_laser_name(top, run.maps[top].wavelength_nm))
        self.ratio_bottom.set(_laser_name(bottom,
                                          run.maps[bottom].wavelength_nm))

    def redraw(self) -> None:
        """The map area as the view asks: one laser, every laser side by
        side, or the ratio of two."""
        run = self.run
        if run is None or self.laser is None:
            return
        mode = self.view_mode.get()
        self.figure.clear()
        self.panels = []
        u0, u1, v0, v1 = run.grid.extent_mm
        width, height = u1 - u0, v1 - v0
        side = mode == "side"
        self.scale_box.state(["!disabled"] if side else ["disabled"])
        for box in (self.ratio_top_box, self.ratio_bottom_box):
            box.state(["!disabled", "readonly"] if mode == "ratio"
                      else ["disabled"])

        if mode == "ratio" and self.ratio_pair is not None:
            top, bottom = self.ratio_pair
            values = viewtools.ratio(self._shown(run.maps[top]),
                                     self._shown(run.maps[bottom]))
            self.unit = ("", 1.0)
            self._add_panel(None, values, 1, 1, 1, width, height,
                            f"laser {top} / laser {bottom}")
            share = f"{viewtools.RATIO_FLOOR_SHARE:.0%}"
            self.caption.configure(
                text=f"laser {top} ({run.maps[top].wavelength_nm:g} nm) over "
                     f"laser {bottom} ({run.maps[bottom].wavelength_nm:g} nm),"
                     f" blank where laser {bottom} gives under {share} of "
                     "its top value")
        elif side:
            lasers = run.lasers
            rows, cols = viewtools.panel_grid(
                len(lasers), self._area_aspect(),
                width / height if viewtools.u_horizontal(self.view)
                else height / width)
            self.unit = self._unit_for(
                [self._shown(run.maps[n]) for n in lasers])
            for k, n in enumerate(lasers):
                m = run.maps[n]
                self._add_panel(n, self._shown(m), rows, cols, k + 1, width,
                                height, self._title(m))
            scale = ("one colour scale" if self.shared_scale.get()
                     else "each its own colour scale")
            self.caption.configure(
                text=f"{len(lasers)} lasers, {scale}: click a map to make "
                     "it the laser the alignment is about")
        else:
            m = run.maps[self.laser]
            self.unit = self._unit_for([self._shown(m)])
            self._add_panel(self.laser, self._shown(m), 1, 1, 1, width,
                            height, self._title(m))
            if self.eqe_shown():
                bits = ([m.no_eqe] if m.no_eqe is not None else
                        [m.response.describe() if m.response else "",
                         m.power.describe() if m.power else ""])
            else:
                bits = [m.status, shift_note(m.result),
                        f"baseline {look.amps(m.result.baseline.offset_a)} "
                        f"subtracted, noise {look.amps(m.noise_a)}"]
                if m.current_range_a is not None:
                    bits.append(f"range {look.amps(m.current_range_a)}")
            self.caption.configure(text=", ".join(b for b in bits if b))

        self._colourbars()
        current = self._current_panel()
        self.axes, self.image = current.axes, current.image
        self.unit_label.configure(text=self.unit[0] or "ratio")
        self._apply_limits()
        if self.line_uv is not None:
            self._set_line(*self.line_uv)
        if self.area_uv is not None:
            self._set_area(*self.area_uv)
        self.canvas.draw_idle()

    def eqe_shown(self) -> bool:
        return self.quantity.get() == "eqe"

    def _shown(self, m: LaserMap) -> np.ndarray:
        """What a laser's panel shows: its photocurrent (A), or its EQE
        (a fraction; all blank where it has none)."""
        if not self.eqe_shown():
            return m.values
        if m.eqe is None:
            return np.full(m.values.shape, np.nan)
        return m.eqe

    def _unit_for(self, maps: list[np.ndarray]) -> tuple[str, float]:
        if self.eqe_shown():
            return EQE_UNIT
        return viewtools.display_unit(np.stack(maps))

    def _title(self, m: LaserMap) -> str:
        if self.eqe_shown() and m.eqe is None:
            return f"{m.label()}: no EQE"
        return m.label()

    def _quantity_label(self) -> str:
        if not self.unit[0]:
            return "ratio" + (" of EQE" if self.eqe_shown() else "")
        if self.eqe_shown():
            return "EQE (%)"
        return f"photocurrent ({self.unit[0]})"

    def _area_aspect(self) -> float:
        """The map area's width over height, less a colour bar's room."""
        widget = self.canvas.get_tk_widget()
        w, h = widget.winfo_width(), widget.winfo_height()
        if w < 50 or h < 50:
            return 1.4
        return 0.85 * w / h

    def _add_panel(self, laser: int | None, values: np.ndarray, rows: int,
                   cols: int, index: int, width: float, height: float,
                   title: str) -> None:
        ax = self.figure.add_subplot(rows, cols, index)
        image = draw_map(ax, values, width, height, self.view,
                         per_unit_a=self.unit[1])
        small = rows * cols > 1
        ax.set_title(title, fontsize=9 if small else 10)
        if small:
            ax.tick_params(labelsize=7)
            ax.xaxis.label.set_size(8)
            ax.yaxis.label.set_size(8)
        self.panels.append(_Panel(laser, ax, image, values))

    def _colourbars(self) -> None:
        label = self._quantity_label()
        if self.view_mode.get() == "side" and not self.shared_scale.get():
            for p in self.panels:
                self.figure.colorbar(p.image, ax=p.axes, shrink=0.85)
        else:
            self.figure.colorbar(self.panels[0].image,
                                 ax=[p.axes for p in self.panels],
                                 label=label,
                                 shrink=0.6 if len(self.panels) > 1 else 1.0)

    def _current_panel(self) -> _Panel:
        for p in self.panels:
            if p.laser == self.laser:
                return p
        return self.panels[0]

    def _panel_of(self, axes: object) -> _Panel | None:
        for p in self.panels:
            if p.axes is axes:
                return p
        return None

    def values(self) -> np.ndarray | None:
        """What the current panel shows: a laser's map (A), or the
        ratio."""
        if self.run is None or self.laser is None:
            return None
        if self.panels:
            return self._current_panel().values
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

    def _limits_for(self, values: list[np.ndarray]
                    ) -> tuple[float, float] | None:
        mode = self.limits_mode.get()
        if mode == "set" and self.limits_a is not None:
            return self.limits_a
        return viewtools.shared_limits(values,
                                       "full" if mode == "full" else "auto")

    def _apply_limits(self) -> None:
        if not self.panels:
            return
        scale = self.unit[1]
        own = self.view_mode.get() == "side" and not self.shared_scale.get()
        if own:
            for p in self.panels:
                limits = self._limits_for([p.values])
                if limits is not None:
                    p.image.set_clim(limits[0] / scale, limits[1] / scale)
            shown = self._limits_for([self._current_panel().values])
        else:
            shown = self._limits_for([p.values for p in self.panels])
            if shown is not None:
                for p in self.panels:
                    p.image.set_clim(shown[0] / scale, shown[1] / scale)
        if shown is not None:
            self.lo_var.set(f"{shown[0] / scale:.4g}")
            self.hi_var.set(f"{shown[1] / scale:.4g}")
        self.canvas.draw_idle()

    def clim(self) -> tuple[float, float] | None:
        """The current panel's colour limits, in the map's unit."""
        return None if self.image is None else self.image.get_clim()

    # ---- the cursor and the profile ----

    def _tools_idle(self) -> bool:
        """Neither zoom nor pan is on in the toolbar."""
        return not str(getattr(self.toolbar, "mode", ""))

    def _motion(self, event: MouseEvent) -> None:
        if self._panel_of(event.inaxes) is None or event.xdata is None \
                or event.ydata is None:
            return
        self.show_cursor(*viewtools.to_uv(self.view, event.xdata,
                                          event.ydata))
        if self._drag_start is not None:
            start = self._drag_start[:2]
            here = viewtools.to_uv(self.view, event.xdata, event.ydata)
            if self.area_mode():
                self._set_area(start, here, compute=False)
            else:
                self._set_line(start, here, compute=False)
            self.canvas.draw_idle()

    def show_cursor(self, u: float, v: float) -> None:
        run = self.run
        if run is None or self.laser is None:
            return
        where = f"u {u:.3f} mm, v {v:.3f} mm"
        if viewtools.pixel_at(run.grid, u, v) is None:
            self.readout.configure(text=f"{where}\noff the map")
            return
        mode = self.view_mode.get()
        if mode == "side":
            lines = [f"laser {n}: {self._reading(run.maps[n], u, v)}"
                     for n in run.lasers]
        elif mode == "ratio" and self.ratio_pair is not None:
            top, bottom = self.ratio_pair
            values = self.values()
            r = (viewtools.value_at(values, run.grid, u, v)
                 if values is not None else None)
            shown = (f"{r:.4g}" if r is not None and np.isfinite(r)
                     else "blank")
            lines = [f"laser {top}: "
                     f"{self._reading(run.maps[top], u, v)}",
                     f"laser {bottom}: "
                     f"{self._reading(run.maps[bottom], u, v)}",
                     f"ratio: {shown}"]
        else:
            lines = [f"{self._reading(run.maps[self.laser], u, v)}"
                     f"  (laser {self.laser})"]
        self.readout.configure(text="\n".join([where, *lines]))

    def _reading(self, m: LaserMap, u: float, v: float) -> str:
        """A laser's value at u, v, as shown: amps, or EQE in %."""
        assert self.run is not None
        values = self._shown(m)
        if self.eqe_shown() and m.eqe is None:
            return "no EQE"
        text = _reading(values, self.run, u, v)
        if not self.eqe_shown():
            return text
        value = viewtools.value_at(values, self.run.grid, u, v)
        if value is None or not np.isfinite(value):
            return text
        return f"EQE {value * 100:.2f} %"

    def _press(self, event: MouseEvent) -> None:
        if (event.button != 1 or self._panel_of(event.inaxes) is None
                or event.xdata is None or event.ydata is None
                or not self._tools_idle() or self.values() is None):
            return
        u, v = viewtools.to_uv(self.view, event.xdata, event.ydata)
        self._drag_start = (u, v, float(event.x), float(event.y))

    def _release(self, event: MouseEvent) -> None:
        start, self._drag_start = self._drag_start, None
        if start is None:
            return
        panel = self._panel_of(event.inaxes)
        if event.xdata is None or event.ydata is None or panel is None:
            self._restore_marks()
            self.canvas.draw_idle()
            return
        here = viewtools.to_uv(self.view, event.xdata, event.ydata)
        moved = abs(event.x - start[2]) + abs(event.y - start[3])
        if moved < MIN_DRAG_PX:
            # A click. Side by side, the map clicked becomes the current
            # laser. In area mode it picks the pixel under it; a line
            # drawn stays as it was.
            if panel.laser is not None and panel.laser != self.laser \
                    and self.view_mode.get() == "side":
                self._pick(panel.laser)
                self.axes, self.image = panel.axes, panel.image
                self._apply_limits()
                self.status(f"laser {panel.laser} picked")
            if self.area_mode():
                self.draw_area(here, here)
                return
            self._restore_marks()
            self.canvas.draw_idle()
            return
        if self.area_mode():
            self.draw_area((start[0], start[1]), here)
        else:
            self.draw_profile((start[0], start[1]), here)

    def _restore_marks(self) -> None:
        """The line and the area as they were (a drag that came to
        nothing)."""
        if self.line_uv is not None:
            self._set_line(*self.line_uv, compute=False)
        else:
            self._remove_line()
        if self.area_uv is not None:
            self._set_area(*self.area_uv, compute=False)
        else:
            self._remove_area()

    def area_mode(self) -> bool:
        return self.pick_mode.get() == "area"

    def _pick_mode_changed(self) -> None:
        """The plot shows what the mode draws: the line's profile, or the
        area's spectrum."""
        self._show_pick()

    def _show_pick(self) -> None:
        if self.area_mode():
            if self.area_uv is not None:
                self._plot_spectrum()
            else:
                self._empty_plot("Click a pixel, or drag across an area, "
                                 "for each laser's value there.")
        elif self.line_uv is not None:
            self._plot_profile(*self.line_uv)
        else:
            self._empty_plot("Drag across the map to draw a line.")

    def _empty_plot(self, note: str) -> None:
        self.profile_axes.clear()
        self.profile_canvas.draw_idle()
        self.profile_note.configure(text=note)
        self.clear_btn.state(["disabled"])

    # ---- the line and its profile ----

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
        for p in self.panels:
            if p.line is None:
                # The map's extent stays: a line past its edge is
                # clipped, not given room.
                (p.line,) = p.axes.plot(
                    [x0, x1], [y0, y1], color=LINE_COLOUR, lw=1.5,
                    marker="o", markersize=4, scalex=False, scaley=False)
            else:
                p.line.set_data([x0, x1], [y0, y1])
        if compute:
            self._plot_profile(start_uv, end_uv)

    def _remove_line(self) -> None:
        for p in self.panels:
            if p.line is not None:
                p.line.remove()
                p.line = None

    def _plot_profile(self, start_uv: tuple[float, float],
                      end_uv: tuple[float, float]) -> None:
        """Each panel's map along the line, kept (`profiles`, `profile`)
        and, in line mode, plotted."""
        run = self.run
        if run is None or not self.panels:
            return
        name, scale = self.unit
        draw = not self.area_mode()
        ax = self.profile_axes
        if draw:
            ax.clear()
        self.profiles = {}
        for p in self.panels:
            prof = viewtools.profile(p.values, run.grid, start_uv, end_uv)
            if p.laser is None:
                if draw:
                    ax.plot(prof.distance_mm, prof.values, lw=1.2,
                            color="#333333")
                self.profile = prof
                continue
            self.profiles[p.laser] = prof
            m = run.maps[p.laser]
            if draw:
                ax.plot(prof.distance_mm, prof.values / scale, lw=1.2,
                        color=wavelength_colour(m.wavelength_nm),
                        label=_laser_name(p.laser, m.wavelength_nm))
        if self.profiles:
            self.profile = self.profiles.get(
                self.laser, next(iter(self.profiles.values())))
        if not draw:
            return
        ax.set_xlabel("distance along the line (mm)")
        ax.set_ylabel(self._quantity_label())
        if len(self.panels) > 1:
            ax.legend(fontsize=7, loc="best")
        else:
            ax.set_title(self.panels[0].axes.get_title(), fontsize=9)
        ax.grid(True, alpha=0.3)
        self.profile_figure.tight_layout()
        self.profile_canvas.draw_idle()
        (u0, v0), (u1, v1) = start_uv, end_uv
        length = self.profile.length_mm if self.profile else 0.0
        self.profile_note.configure(
            text=f"({u0:.3f}, {v0:.3f}) to ({u1:.3f}, {v1:.3f}) mm, "
                 f"{length:.3f} mm long")
        self.clear_btn.state(["!disabled"])

    def clear_profile(self) -> None:
        self.line_uv = None
        self.profile = None
        self.profiles = {}
        self._remove_line()
        if not self.area_mode():
            self._show_pick()
        self.canvas.draw_idle()

    # ---- the area and its spectrum ----

    def draw_area(self, corner_a: tuple[float, float],
                  corner_b: tuple[float, float]) -> None:
        """The rectangle between two corners on the sample (one pixel,
        for a click), and every laser's value over it."""
        self.area_uv = (corner_a, corner_b)
        self._set_area(corner_a, corner_b)
        self.canvas.draw_idle()

    def _area_bounds(self, corner_a: tuple[float, float],
                     corner_b: tuple[float, float]
                     ) -> tuple[np.ndarray, tuple[float, float, float, float]]:
        """The area's pixels, and the rectangle their edges make (u0, u1,
        v0, v1): what the drawn box shows is what is counted."""
        assert self.run is not None
        grid = self.run.grid
        mask = viewtools.area_mask(grid, corner_a, corner_b)
        if not mask.any():
            u0, u1 = sorted((corner_a[0], corner_b[0]))
            v0, v1 = sorted((corner_a[1], corner_b[1]))
            return mask, (u0, u1, v0, v1)
        rows = np.flatnonzero(mask.any(axis=1))
        cols = np.flatnonzero(mask.any(axis=0))
        return mask, (cols[0] * grid.pixel_mm, (cols[-1] + 1) * grid.pixel_mm,
                      rows[0] * grid.pitch_mm, (rows[-1] + 1) * grid.pitch_mm)

    def _set_area(self, corner_a: tuple[float, float],
                  corner_b: tuple[float, float], *,
                  compute: bool = True) -> None:
        if self.run is None:
            return
        _, (u0, u1, v0, v1) = self._area_bounds(corner_a, corner_b)
        x0, y0 = viewtools.to_xy(self.view, u0, v0)
        x1, y1 = viewtools.to_xy(self.view, u1, v1)
        corner = (min(x0, x1), min(y0, y1))
        w, h = abs(x1 - x0), abs(y1 - y0)
        for p in self.panels:
            if p.area is None:
                p.area = Rectangle(corner, w, h, fill=False,
                                   edgecolor=LINE_COLOUR, linewidth=1.5,
                                   linestyle="--")
                p.axes.add_patch(p.area)
            else:
                p.area.set_xy(corner)
                p.area.set_width(w)
                p.area.set_height(h)
        if compute:
            self._plot_spectrum()

    def _remove_area(self) -> None:
        for p in self.panels:
            if p.area is not None:
                p.area.remove()
                p.area = None

    def spectrum_unit(self) -> tuple[str, float]:
        """The spectrum's unit: EQE in %, or the photocurrent's for all
        the run's lasers together."""
        if self.eqe_shown():
            return EQE_UNIT
        assert self.run is not None
        return viewtools.display_unit(self.run.stack())

    def _plot_spectrum(self) -> None:
        """Every laser's value over the area, at its wavelength: the
        median and the spread, in area mode plotted."""
        run = self.run
        if run is None or self.area_uv is None:
            return
        mask, (u0, u1, v0, v1) = self._area_bounds(*self.area_uv)
        maps = {n: (m.wavelength_nm, self._shown(m))
                for n, m in run.maps.items()}
        self.spectrum = viewtools.spectrum(maps, mask)
        if not self.area_mode():
            return
        name, scale = self.spectrum_unit()
        ax = self.profile_axes
        ax.clear()
        points = self.spectrum
        if points:
            nm = [p.wavelength_nm for p in points]
            ax.plot(nm, [p.median / scale for p in points], color="#999999",
                    lw=1, zorder=1)
            for p in points:
                colour = wavelength_colour(p.wavelength_nm)
                ax.errorbar([p.wavelength_nm], [p.median / scale],
                            yerr=[[(p.median - p.low) / scale],
                                  [(p.high - p.median) / scale]],
                            fmt="o", color=colour, ecolor=colour,
                            markeredgecolor="#333333", markersize=7,
                            capsize=3, zorder=2)
                ax.annotate(str(p.laser), (p.wavelength_nm, p.median / scale),
                            textcoords="offset points", xytext=(6, 4),
                            fontsize=7, color="#333333")
        ax.set_xlabel("wavelength (nm)")
        ax.set_ylabel("EQE (%)" if self.eqe_shown()
                      else f"photocurrent ({name})")
        ax.set_xlim(400, 900)
        ax.grid(True, alpha=0.3)
        pixels = int(mask.sum())
        where = (f"pixel at ({u0:.3f}, {v0:.3f}) mm" if pixels == 1 else
                 f"{u1 - u0:.3f} x {v1 - v0:.3f} mm, {pixels} pixels")
        ax.set_title(where, fontsize=9)
        self.profile_figure.tight_layout()
        self.profile_canvas.draw_idle()
        missing = [n for n in run.lasers
                   if n not in {p.laser for p in points}]
        note = where + ("; median and 16-84 % spread" if pixels > 1 else "")
        if missing:
            why = "no EQE" if self.eqe_shown() else "no values there"
            note += f"; {why}: laser " + ", ".join(map(str, missing))
        self.profile_note.configure(text=note)
        self.clear_btn.state(["!disabled"])

    def clear_area(self) -> None:
        self.area_uv = None
        self.spectrum = []
        self._remove_area()
        if self.area_mode():
            self._show_pick()
        self.canvas.draw_idle()

    def clear_current(self) -> None:
        """Clear: what the mode draws."""
        if self.area_mode():
            self.clear_area()
        else:
            self.clear_profile()

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


def _laser_name(laser: int, nm: float) -> str:
    return f"{laser}: {nm:g} nm"


def _laser_of(name: str) -> int | None:
    """The laser number from a name `_laser_name` made."""
    head = name.split(":", 1)[0].strip()
    return int(head) if head.isdigit() else None


def _reading(values: np.ndarray, run: RunFolder, u: float, v: float) -> str:
    """A map's value at u, v for the cursor readout. An empty pixel is
    filled in the picture from its neighbours (`store/image.
    fill_short_gaps`), never in the data."""
    value = viewtools.value_at(values, run.grid, u, v)
    if value is None:
        return "off the map"
    return look.amps(value) if np.isfinite(value) else "no samples here"


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
