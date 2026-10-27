"""
The run column of the window: how far the run has got, and its maps.

One tab per laser. While a laser scans, its tab shows the live map,
built row by row and not corrected for the serpentine shift (D18); when
it ends, the map built from its file replaces it, as the PNG beside the
file is drawn. "Open run file..." draws any earlier run's map the same
way. Maps are on white paper in both modes, as SMUniversal's plots are.

Redrawing is throttled to `REDRAW_MS`, and big maps are averaged down
for the screen (`livemap.shrink`), so a fast run doesn't swamp the Pi.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import TYPE_CHECKING

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from multilbic.gui import look
from multilbic.gui.livemap import LiveMap, RunProgress, shrink
from multilbic.gui.plan_view import PlanView
from multilbic.gui.worker import (
    Event,
    MapEvent,
    RowEvent,
    RunEnded,
    RunStarted,
    State,
)
from multilbic.run.session import duration, estimate_run
from multilbic.store.image import draw_map, image_data, shift_note

if TYPE_CHECKING:
    from matplotlib.colorbar import Colorbar
    from matplotlib.image import AxesImage

    from multilbic.gui.app import App
    from multilbic.scan.mapping import MapResult

REDRAW_MS = 500
CLOCK_MS = 1000


class MapTab:
    """One laser's map: live while it scans, then the finished one."""

    def __init__(self, notebook: ttk.Notebook, title: str,
                 view: tuple[str, str], colour: str | None = None):
        self.view = view
        self.frame = ttk.Frame(notebook, padding=4)
        if colour:
            notebook.add(self.frame, text=f" {title}", compound="left",
                         image=look.swatch(notebook, colour, size=12))
        else:
            notebook.add(self.frame, text=title)
        self.figure = Figure(figsize=(6, 5), dpi=100, facecolor="white")
        self.axes = self.figure.add_subplot()
        self.canvas = FigureCanvasTkAgg(self.figure, master=self.frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.caption = ttk.Label(self.frame, text="", style="Hint.TLabel")
        self.caption.pack(anchor="w", pady=(4, 0))
        self.image: AxesImage | None = None
        self.colorbar: Colorbar | None = None
        self.final = False

    def show_live(self, live: LiveMap) -> None:
        values = live.values()
        if self.image is None:
            self._start(values, live.width_mm, live.height_mm)
        assert self.image is not None
        data = image_data(values, self.view)
        self.image.set_data(data)
        _clim(self.image, data)
        self.caption.configure(
            text=f"live: {live.rows_done} of {live.n_rows} rows, not "
                 "corrected for the serpentine shift")
        self.canvas.draw_idle()

    def show_final(self, result: MapResult, status: str) -> None:
        grid = result.grid
        rows, cols = grid.values.shape
        self._start(shrink(grid.values), cols * grid.pixel_mm,
                    rows * grid.pitch_mm)
        assert self.image is not None
        _clim(self.image, self.image.get_array())
        self.final = True
        self.caption.configure(
            text=f"{status}: {shift_note(result)}, baseline "
                 f"{result.baseline.offset_a * 1e9:.2f} nA subtracted")
        self.canvas.draw_idle()

    def note(self, text: str) -> None:
        self.caption.configure(text=text)

    def _start(self, values: np.ndarray, width: float, height: float) -> None:
        if self.colorbar is not None:
            self.colorbar.remove()
        self.axes.clear()
        image = draw_map(self.axes, values, width, height, self.view)
        self.image = image
        self.colorbar = self.figure.colorbar(image, ax=self.axes,
                                             label="photocurrent (nA)")
        self.figure.tight_layout()


def _clim(image, data) -> None:  # noqa: ANN001
    finite = np.asarray(data)[np.isfinite(data)]
    if finite.size:
        lo, hi = float(finite.min()), float(finite.max())
        image.set_clim(lo, hi if hi > lo else lo + 1e-3)


class RunPanel:
    def __init__(self, app: App, parent: tk.Misc):
        self.app = app
        self.frame = look.section(parent, "Run")
        self.headline = ttk.Label(self.frame, text="No run yet",
                                  style="Title.TLabel")
        self.headline.pack(anchor="w")
        self.bar = ttk.Progressbar(self.frame, maximum=1.0,
                                   mode="determinate")
        self.bar.pack(fill="x", pady=(6, 2))
        self.timing = ttk.Label(self.frame, text="", style="Hint.TLabel")
        self.timing.pack(anchor="w")
        self.notebook = ttk.Notebook(self.frame)
        self.notebook.pack(fill="both", expand=True, pady=(8, 6))
        # The first tab, always there: the run as set up, before it runs.
        self.plan_view = PlanView(app, self.notebook)
        bottom = ttk.Frame(self.frame)
        bottom.pack(fill="x")
        self.open_btn = ttk.Button(bottom, text="Open run file...",
                                   command=self.open_file)
        self.open_btn.pack(side="left")
        self.folder_btn = ttk.Button(bottom, text="Open folder",
                                     command=self.open_folder)
        self.folder_btn.pack(side="left", padx=(6, 0))
        self.outcome = ttk.Label(bottom, text="", style="Hint.TLabel")
        self.outcome.pack(side="left", padx=(10, 0))

        self.tabs: dict[int, MapTab] = {}
        self.live: dict[int, LiveMap] = {}
        self.progress: RunProgress | None = None
        self.folder: Path | None = None
        self.running = False
        self._dirty: set[int] = set()
        self._redraw_id: str | None = None
        self._clock_id: str | None = None
        self._loaded: queue.Queue = queue.Queue()
        self.refresh()

    # ---- events ----

    def handle(self, event: Event) -> None:
        if isinstance(event, RunStarted):
            self._started(event)
        elif isinstance(event, RowEvent):
            self._block(event)
        elif isinstance(event, MapEvent):
            tab = self.tabs.get(event.laser.laser)
            if tab is not None:
                self._dirty.discard(event.laser.laser)
                tab.show_final(event.result, event.laser.status)
        elif isinstance(event, RunEnded):
            self._ended(event)

    def _started(self, event: RunStarted) -> None:
        plan_tab = str(self.plan_view.frame)
        for tab_id in self.notebook.tabs():
            if tab_id != plan_tab:
                self.notebook.forget(tab_id)
        self.tabs.clear()
        self.live.clear()
        machine = self.app.machine
        view = machine.display.view
        for plan in event.plans:
            self.tabs[plan.laser] = MapTab(
                self.notebook, f"{plan.laser}: {plan.wavelength_nm} nm", view,
                colour=self.app.laser_colour(plan.laser))
            self.tabs[plan.laser].note("waiting")
            self.live[plan.laser] = LiveMap(plan, machine.mains_hz)
        estimate = estimate_run(list(event.plans), event.request, machine)
        fixed = [e.total_s - e.rows_s for e in estimate.lasers]
        self.progress = RunProgress(
            event.plans, estimate.total_s, time.monotonic(),
            sum(fixed) / len(fixed))
        self.folder = event.folder
        self.running = True
        self.headline.configure(text="Homing")
        self.outcome.configure(text=str(event.folder), style="Hint.TLabel")
        self._tick()
        self.refresh()

    def _block(self, event: RowEvent) -> None:
        block = event.row
        live = self.live.get(block.laser)
        if live is None or self.progress is None:
            return
        first = not (live.baseline_done or live.warmup_done or live.rows_done)
        restarts = live.restarts
        live.add(block)
        self.progress.block(block, time.monotonic())
        tab = self.tabs[block.laser]
        name = f"Laser {block.laser} ({live.wavelength_nm} nm)"
        if first:
            self.notebook.select(tab.frame)
        if live.restarts > restarts:
            # D26: the range clipped; the laser starts again one up.
            self.headline.configure(
                text=f"{name}: range clipped, starting again one up")
            tab.note("the range clipped: the map starts again one range "
                     "up (the clipped attempt is kept in its own file)")
            self._dirty.add(block.laser)
            self._schedule_redraw()
        elif block.row >= 0:
            self.headline.configure(
                text=f"{name}: row {block.row + 1} of {block.rows}")
            self._dirty.add(block.laser)
            self._schedule_redraw()
        elif live.baseline_done and not live.warmup_done:
            self.headline.configure(text=f"{name}: warming up")
            tab.note("baseline done; the laser warms up before the first row")
        else:
            self.headline.configure(text=f"{name}: rows starting")

    def _ended(self, event: RunEnded) -> None:
        outcome = event.outcome
        self.running = False
        status = outcome.status
        self.headline.configure(text=f"Run {status}")
        if status == "complete":
            self.bar.configure(value=1.0)
        for result in outcome.lasers:
            tab = self.tabs.get(result.laser)
            if tab is not None and not tab.final:
                tab.note(f"{result.status}: no map (no finished rows)")
        for laser, tab in self.tabs.items():
            if laser not in {r.laser for r in outcome.lasers}:
                tab.note("not started")
        self.outcome.configure(
            text=str(outcome.folder),
            style="Hint.TLabel" if status == "complete" else "Bad.TLabel")
        self._redraw()
        self._tick()
        self.refresh()

    # ---- redrawing ----

    def _schedule_redraw(self) -> None:
        if self._redraw_id is None:
            self._redraw_id = self.app.root.after(REDRAW_MS, self._redraw)

    def _redraw(self) -> None:
        self._redraw_id = None
        for laser in list(self._dirty):
            tab = self.tabs.get(laser)
            if tab is not None and not tab.final:
                tab.show_live(self.live[laser])
        self._dirty.clear()

    def _tick(self) -> None:
        if self._clock_id is not None:
            self.app.root.after_cancel(self._clock_id)
            self._clock_id = None
        p = self.progress
        if p is None:
            return
        now = time.monotonic()
        elapsed = now - p.started_s
        if self.running:
            self.bar.configure(value=p.fraction(now))
            left = p.remaining_s(now)
            self.timing.configure(
                text=f"{duration(elapsed)} so far, about {duration(left)} "
                     f"left; {p.rows_done} of {p.rows_total} rows")
            self._clock_id = self.app.root.after(CLOCK_MS, self._tick)
        else:
            self.timing.configure(
                text=f"took {duration(elapsed)}; {p.rows_done} of "
                     f"{p.rows_total} rows")

    # ---- earlier runs ----

    def open_file(self) -> None:
        start = self.folder.parent if self.folder else Path.home()
        path = filedialog.askopenfilename(
            parent=self.app.root, title="Open a run file",
            initialdir=str(start),
            filetypes=[("Run file", "*.csv"), ("All files", "*")],
        )
        if not path:
            return
        self.app.status(f"building the map of {path}")
        threading.Thread(target=self._load, args=(Path(path),),
                         name="open-run", daemon=True).start()
        self._poll_loaded()

    def _load(self, path: Path) -> None:
        """On its own thread: reading and mapping a big file takes a
        while. Hands the result back through a queue."""
        from multilbic.scan.mapping import build_map
        from multilbic.store.runfile import read_run

        try:
            run = read_run(path)
            result = build_map(run.scan_data())
            self._loaded.put((path, result, run.header.get("status", "?")))
        except Exception as exc:
            self._loaded.put((path, exc, ""))

    def _poll_loaded(self) -> None:
        try:
            path, result, status = self._loaded.get_nowait()
        except queue.Empty:
            self.app.root.after(100, self._poll_loaded)
            return
        if isinstance(result, Exception):
            self.app.status(f"{path.name}: {result}", error=True)
            return
        tab = MapTab(self.notebook, path.stem, self.app.machine.display.view)
        tab.show_final(result, f"{path.parent.name}, {status}")
        self.notebook.select(tab.frame)
        self.app.status(f"opened {path}")

    def open_folder(self) -> None:
        if self.folder is None:
            return
        # The folder is the run's own, made by the session: not input.
        try:
            if sys.platform == "win32":
                os.startfile(self.folder)  # type: ignore[attr-defined,unused-ignore]  # noqa: S606, E501
            else:
                subprocess.Popen(["xdg-open", str(self.folder)])  # noqa: S603, S607
        except Exception as exc:
            self.app.status(f"open folder: {exc}", error=True)

    def refresh(self) -> None:
        running = self.app.state in (State.RUNNING, State.STOPPING)
        # Mapping a big file is heavy: not while a run needs the Pi.
        self.open_btn.state(["disabled"] if running else ["!disabled"])
        self.folder_btn.state(
            ["!disabled"] if self.folder is not None else ["disabled"])
