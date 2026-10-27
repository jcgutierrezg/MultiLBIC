"""
The sample column of the window: calibration, then run setup.

Calibration is the command line's `calibrate` as three steps - find the
corner, give the size, check the outline - with a drawing of where the
sample is. Run setup is `multilbic run`'s options, checked on every
keystroke (`runform.plan_form`), and Start, which asks first (D20).
"""

from __future__ import annotations

import functools
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from multilbic.gui import look
from multilbic.gui.runform import FormError, RunForm, RunPlan, eta, plan_form
from multilbic.gui.worker import (
    CalibrationChanged,
    Event,
    LaserChanged,
    Position,
    State,
)
from multilbic.run.ranges import RangeCheck, check_duration_s
from multilbic.run.session import (
    CURRENT_RANGES,
    REAL_RUNS,
    SIM_RUNS,
    range_name,
)
from multilbic.scan.geometry import Calibration, SampleFrame, xy_to_ab

if TYPE_CHECKING:
    from multilbic.gui.app import App

#: Where calibration files are offered first: ~/cal on the Pi.
CAL_DIRS = (Path.home() / "cal", Path.home())
#: Screen direction of each `[display]` word, canvas y pointing down.
VECTORS = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}
PLAN_DELAY_MS = 150


class CalibrationPanel:
    def __init__(self, app: App, parent: tk.Misc):
        self.app = app
        ref = app.machine.geometry.reference_laser
        self.frame = look.section(parent, "Calibration")
        self.calibration: Calibration | None = None
        self.corner_set = False
        self._loading = False

        name = ttk.Frame(self.frame)
        name.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        ttk.Label(name, text="Sample").pack(side="left")
        self.sample = tk.StringVar(master=app.root, value="")
        self.sample.trace_add("write", lambda *a: app.calibration_changed())
        self.sample_entry = ttk.Entry(name, textvariable=self.sample,
                                      width=28)
        self.sample_entry.pack(side="left", padx=(8, 0))

        # 1: the corner
        ttk.Label(self.frame, text="1", style="Accent.Bold.TLabel").grid(
            row=1, column=0, sticky="nw", padx=(0, 8))
        one = ttk.Frame(self.frame)
        one.grid(row=1, column=1, sticky="w")
        self.start_btn = ttk.Button(one, text="Start",
                                    command=self.start)
        self.start_btn.pack(side="left")
        self.here_btn = ttk.Button(one, text="Set corner here",
                                   command=self.here)
        self.here_btn.pack(side="left", padx=(6, 0))
        # Two short lines: one long one ran past the panel on the Pi.
        self.corner_label = ttk.Label(one, text="", style="Hint.TLabel",
                                      justify="left")
        self.corner_label.pack(side="left", padx=(10, 0))
        ttk.Label(
            self.frame, style="Small.Hint.TLabel", wraplength=460,
            justify="left",
            text=f"Start homes the stage and lights laser {ref} over the "
                 "AB centre. Jog until the spot is on the sample's "
                 "top-right corner as you look at it, then Set corner here.",
        ).grid(row=2, column=1, columnspan=2, sticky="w", pady=(2, 6))

        # 2: the size
        ttk.Label(self.frame, text="2", style="Accent.Bold.TLabel").grid(
            row=3, column=0, sticky="nw", padx=(0, 8))
        two = ttk.Frame(self.frame)
        two.grid(row=3, column=1, sticky="w", pady=(0, 6))
        ttk.Label(two, text="width (A)").pack(side="left")
        self.width = ttk.Entry(two, width=7)
        self.width.pack(side="left", padx=(4, 10))
        ttk.Label(two, text="height (B)").pack(side="left")
        self.height = ttk.Entry(two, width=7)
        self.height.pack(side="left", padx=(4, 4))
        ttk.Label(two, text="mm").pack(side="left")
        self.size_btn = ttk.Button(two, text="Set size",
                                   command=self.set_size)
        self.size_btn.pack(side="left", padx=(10, 0))

        # 3: the outline
        ttk.Label(self.frame, text="3", style="Accent.Bold.TLabel").grid(
            row=4, column=0, sticky="nw", padx=(0, 8))
        three = ttk.Frame(self.frame)
        three.grid(row=4, column=1, sticky="w", pady=(0, 6))
        self.trace_btn = ttk.Button(three, text="Trace the outline",
                                    command=self.trace)
        self.trace_btn.pack(side="left")
        ttk.Label(three, style="Small.Hint.TLabel",
                  text="the spot runs round the sample and back to the "
                       "corner").pack(side="left", padx=(10, 0))

        # 4: the sample's current ranges (D25)
        ttk.Label(self.frame, text="4", style="Accent.Bold.TLabel").grid(
            row=5, column=0, sticky="nw", padx=(0, 8))
        four = ttk.Frame(self.frame)
        four.grid(row=5, column=1, sticky="w", pady=(0, 6))
        self.ranges_btn = ttk.Button(four, text="Check ranges",
                                     command=self.check_ranges)
        self.ranges_btn.pack(side="left")
        self.ranges_label = ttk.Label(
            four, style="Small.Hint.TLabel", justify="left", wraplength=330,
            text="each laser ticked in Run setup, on a grid over the "
                 "sample")
        self.ranges_label.pack(side="left", padx=(10, 0))
        self.ranges: dict[int, RangeCheck] = {}

        files = ttk.Frame(self.frame)
        files.grid(row=6, column=1, sticky="w", pady=(2, 6))
        self.save_btn = ttk.Button(files, text="Save...", command=self.save)
        self.save_btn.pack(side="left")
        self.load_btn = ttk.Button(files, text="Load...", command=self.load)
        self.load_btn.pack(side="left", padx=(6, 0))
        self.corner_btn = ttk.Button(files, text="Go to corner",
                                     command=self.to_corner)
        self.corner_btn.pack(side="left", padx=(6, 0))
        self.file_label = ttk.Label(files, text="not saved",
                                    style="Hint.TLabel")
        self.file_label.pack(side="left", padx=(10, 0))

        self.preview = OutlinePreview(app, self.frame)
        self.preview.canvas.grid(row=7, column=0, columnspan=3, sticky="ew",
                                 pady=(4, 0))
        self.frame.columnconfigure(1, weight=1)

    # ---- actions ----

    def start(self) -> None:
        if not self.app.worker.start_calibration():
            self.app.refused("start calibration")

    def here(self) -> None:
        if not self.app.worker.here():
            self.app.refused("set corner")

    def set_size(self) -> None:
        try:
            width = float(self.width.get())
            height = float(self.height.get())
        except ValueError:
            self.app.status("size: width and height in mm, e.g. 10 and 10",
                            error=True)
            return
        if not self.app.worker.set_size(width, height):
            self.app.refused("set size")

    def trace(self) -> None:
        if not self.app.worker.trace():
            self.app.refused("trace")

    def to_corner(self) -> None:
        if not self.app.worker.to_corner():
            self.app.refused("go to corner")

    def check_ranges(self, lasers: list[int] | None = None) -> None:
        """Each laser's current range on the sample (D25), for the
        lasers ticked in Run setup unless told which. Asks first: the
        stage moves and the lasers come on in turn."""
        setup = self.app.setup
        lasers = lasers or list(setup.form().lasers)
        if not lasers:
            self.app.status("check ranges: tick a laser in Run setup",
                            error=True)
            return
        if self.calibration is None:
            self.app.status("check ranges: set the corner and the size "
                            "first", error=True)
            return
        try:
            bias = float(setup.fields["bias_v"].get())
        except ValueError:
            self.app.status("check ranges: Bias (V) is not a number",
                            error=True)
            return
        c = self.calibration
        frame = SampleFrame.centred(self.app.machine.ab.centre_mm,
                                    c.width_mm, c.height_mm)
        named = ", ".join(str(n) for n in lasers)
        if not messagebox.askokcancel(
            "Check current ranges?",
            f"Lasers {named}, in turn: XY places the sample as a run will, "
            "the laser comes on, and the stage runs a grid of six lines "
            f"over the sample, reading the photocurrent at {bias:g} V. "
            f"About {eta(check_duration_s(frame, len(lasers)))}.\n\n"
            "It ends with the reference laser back on the corner.",
            parent=self.app.root,
        ):
            return
        if not self.app.worker.check_ranges(lasers, bias):
            self.app.refused("check ranges")

    def save(self) -> None:
        name = self.sample.get().strip() or "sample"
        path = filedialog.asksaveasfilename(
            parent=self.app.root, title="Save the calibration",
            initialdir=str(_cal_dir()), initialfile=f"{name}.json",
            defaultextension=".json",
            filetypes=[("Calibration", "*.json"), ("All files", "*")],
        )
        if path and not self.app.worker.save(path, sample=name):
            self.app.refused("save")

    def load(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.app.root, title="Load a calibration",
            initialdir=str(_cal_dir()),
            filetypes=[("Calibration", "*.json"), ("All files", "*")],
        )
        if not path:
            return
        self._loading = True
        if not self.app.worker.load(path):
            self._loading = False
            self.app.refused("load")

    # ---- redrawing ----

    def handle(self, event: Event) -> None:
        if isinstance(event, CalibrationChanged):
            self.calibration = event.calibration
            self.corner_set = event.corner_xy is not None
            if event.corner_xy is not None and event.corner_ab is not None:
                (x, y), (a, b) = event.corner_xy, event.corner_ab
                self.corner_label.configure(
                    text=f"X{x:.3f} Y{y:.3f}\nA{a:.4f} B{b:.4f}")
            if event.size is not None:
                for entry, value in zip((self.width, self.height),
                                        event.size, strict=True):
                    entry.delete(0, "end")
                    entry.insert(0, f"{value:g}")
            if self._loading or not self.sample.get().strip():
                self.sample.set(event.sample)
                self._loading = False
            self.file_label.configure(
                text=str(event.saved) if event.saved else "not saved")
            self.preview.outline = event.outline
            self.preview.draw()
            self.ranges = dict(event.ranges)
            self.ranges_label.configure(text=_ranges_text(self.ranges))
            self.app.calibration_changed()
        elif isinstance(event, Position):
            self.preview.position = event.xyab
            self.preview.draw()
        elif isinstance(event, LaserChanged):
            self.preview.laser = event.laser
            self.preview.draw()

    def refresh(self) -> None:
        app = self.app
        usable = app.state in (State.IDLE, State.MOVING)
        moving = usable and app.homed
        _enable(self.start_btn, usable)
        _enable(self.load_btn, usable)
        _enable(self.size_btn, usable)
        _enable(self.here_btn, moving)
        _enable(self.corner_btn, moving and self.corner_set)
        _enable(self.trace_btn, moving and self.calibration is not None)
        _enable(self.ranges_btn, moving and self.calibration is not None)
        _enable(self.save_btn, usable and self.calibration is not None)

    def current(self) -> Calibration | None:
        """The calibration, with the sample name as typed now."""
        if self.calibration is None:
            return None
        name = self.sample.get().strip()
        return replace(self.calibration, sample=name) if name \
            else self.calibration


class OutlinePreview:
    """AB's safe range, the sample as a run places it, the corner, and
    the spot, drawn as the operator sees the stage (`[display]`).

    The spot is drawn where it falls in the placed frame: XY away from
    the placement moves it as AB would (`xy_to_ab`), and a laser other
    than the reference one sits its `xy_centre_mm` offset away."""

    #: Tall enough to see the sample (it zooms to it), short enough that
    #: the column, with calibration's step 4 and the ranges, fits the
    #: Pi's 944 px window.
    SIZE = 150
    MARGIN = 18

    def __init__(self, app: App, parent: tk.Misc):
        self.app = app
        self.canvas = tk.Canvas(parent, height=self.SIZE,
                                highlightthickness=0, borderwidth=0)
        self.outline: tuple[tuple[float, float],
                            list[tuple[float, float]]] | None = None
        self.position: dict[str, float] | None = None
        self.laser = 0
        self.canvas.bind("<Configure>", lambda e: self.draw())
        app.theme.on_change(lambda t: self.draw(), widget=self.canvas)

    def spot_ab(self) -> tuple[float, float] | None:
        """Where the spot is, in the placed frame's AB."""
        p = self.position
        if p is None:
            return None
        if self.outline is None:
            return p["A"], p["B"]
        machine = self.app.machine
        g = machine.geometry
        (xp, yp), _ = self.outline
        ref = machine.laser(g.reference_laser).xy_centre_mm
        lit = self.laser or g.reference_laser
        try:
            centre = machine.laser(lit).xy_centre_mm
        except KeyError:
            centre = ref
        # Under laser `lit`, the sample point under the reference laser
        # at XY is the one under `lit` at XY + (centre - ref).
        dx = p["X"] - xp - (centre[0] - ref[0])
        dy = p["Y"] - yp - (centre[1] - ref[1])
        da, db = xy_to_ab(g.x_along, g.y_along, dx, dy)
        return p["A"] + da, p["B"] + db

    def draw(self) -> None:
        c = self.canvas
        theme = self.app.theme
        pal = theme.palette
        c.configure(background=pal.field)
        c.delete("all")
        width = max(c.winfo_width(), 2 * self.MARGIN + 10)
        height = max(c.winfo_height(), 2 * self.MARGIN + 10)
        ab = self.app.machine.ab
        lo, hi = ab.safe_min_mm, ab.safe_max_mm
        spot = self.spot_ab()
        points = self.outline[1] if self.outline is not None else None
        ca, cb, span = view_box(points, spot, lo, hi)
        scale = (min(width, height) - 2 * self.MARGIN) / span
        d = self.app.machine.display
        ux, uy = VECTORS[d.u_points]
        vx, vy = VECTORS[d.v_points]

        def at(a: float, b: float) -> tuple[float, float]:
            return (width / 2 + ((a - ca) * ux + (b - cb) * vx) * scale,
                    height / 2 + ((a - ca) * uy + (b - cb) * vy) * scale)

        corners = [at(lo, lo), at(hi, lo), at(hi, hi), at(lo, hi)]
        c.create_polygon(*[v for xy in corners for v in xy],
                         outline=pal.rule, fill="", dash=(3, 3))
        if self.outline is not None:
            _, points = self.outline
            flat = [v for a, b in points[:-1] for v in at(a, b)]
            c.create_polygon(*flat, outline=theme.accent,
                             fill=look.blend_soft(theme), width=2)
            x, y = at(*points[0])
            c.create_oval(x - 4, y - 4, x + 4, y + 4, fill=theme.accent,
                          outline="")
            c.create_text(x, y - 12, text="corner", fill=pal.ink2,
                          font="SMUSmall")
        if spot is not None:
            x, y = at(*spot)
            lit = self.laser != 0
            colour = self.app.laser_colour(self.laser) if lit else ""
            r = 6
            # Drawn in the lit laser's colour; a ring keeps a dark one
            # (infrared) visible.
            c.create_oval(x - r, y - r, x + r, y + r, width=2,
                          outline=look.RING if lit else pal.muted,
                          fill=colour)
            c.create_line(x - 2 * r, y, x + 2 * r, y, fill=pal.ink2)
            c.create_line(x, y - 2 * r, x, y + 2 * r, fill=pal.ink2)
        arrow = {"left": "←", "right": "→", "up": "↑",
                 "down": "↓"}
        c.create_text(
            6, height - 6, anchor="sw", fill=pal.muted, font="SMUSmall",
            text=f"+A {arrow[d.u_points]}   +B {arrow[d.v_points]}"
                 + ("   dashed: AB's safe range" if points is None else ""),
        )
        # A scale bar, bottom right.
        bar_mm = scale_bar_mm(span)
        x1, y1 = width - 10, height - 10
        x0 = x1 - bar_mm * scale
        c.create_line(x0, y1, x1, y1, fill=pal.ink2, width=2)
        c.create_text((x0 + x1) / 2, y1 - 4, anchor="s", fill=pal.ink2,
                      font="SMUSmall", text=f"{bar_mm:g} mm")


def view_box(
    outline: list[tuple[float, float]] | None,
    spot: tuple[float, float] | None,
    safe_lo: float,
    safe_hi: float,
) -> tuple[float, float, float]:
    """What the preview shows: (centre A, centre B, span) in mm. The
    whole safe range until there is an outline; then the sample and the
    spot, with room round them, so a 2 mm sample isn't a speck."""
    if not outline:
        middle = (safe_lo + safe_hi) / 2
        return middle, middle, safe_hi - safe_lo
    points = list(outline) + ([spot] if spot is not None else [])
    a_lo, a_hi = min(p[0] for p in points), max(p[0] for p in points)
    b_lo, b_hi = min(p[1] for p in points), max(p[1] for p in points)
    size = max(a_hi - a_lo, b_hi - b_lo)
    span = min(size + 2 * max(0.5, 0.25 * size), safe_hi - safe_lo + 2)
    return (a_lo + a_hi) / 2, (b_lo + b_hi) / 2, span


def scale_bar_mm(span: float) -> float:
    """A round length near a fifth of the view."""
    target = span / 5
    for length in (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20):
        if length >= target:
            return float(length)
    return 20.0


class RunSetupPanel:
    def __init__(self, app: App, parent: tk.Misc):
        self.app = app
        self.frame = look.section(parent, "Run setup")
        self.plan: RunPlan | None = None
        self._after: str | None = None
        self._show_plan_tab = False
        form = RunForm()

        lasers = ttk.Frame(self.frame)
        lasers.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))
        ttk.Label(lasers, text="Lasers").grid(row=0, column=0, sticky="nw",
                                              padx=(0, 10))
        self.laser_vars: dict[int, tk.BooleanVar] = {}
        self.laser_boxes: dict[int, ttk.Checkbutton] = {}
        for i, laser in enumerate(app.machine.lasers):
            ticked = tk.BooleanVar(master=app.root,
                                   value=laser.number in form.lasers)
            box = ttk.Checkbutton(
                lasers, variable=ticked, command=self._lasers_changed,
                text=f"{laser.number} ({laser.wavelength_nm})"
                     + ("" if laser.measured else " *"),
                image=look.swatch(lasers, app.laser_colour(laser.number),
                                  size=10),
                compound="left",
            )
            # Two rows of three, the revolver's two groups.
            box.grid(row=i // 3, column=1 + i % 3, sticky="w",
                     padx=(0, 14), pady=1)
            self.laser_vars[laser.number] = ticked
            self.laser_boxes[laser.number] = box
        self.allow = tk.BooleanVar(master=app.root, value=False)
        self.allow_box = ttk.Checkbutton(
            self.frame, variable=self.allow, command=self.changed,
            text="allow lasers marked * (position not measured)")
        self.allow_box.grid(row=1, column=0, columnspan=4, sticky="w")

        # Each ticked laser's current range (D15 revised, D25): checked
        # on the sample at calibration, set here by hand, or a guess
        # (the default range). On its own line: next to the laser boxes
        # it would not fit the Pi's column.
        numbers = [laser.number for laser in app.machine.lasers]
        self.range_vars = {n: tk.StringVar(master=app.root,
                                           value=form.current_range)
                           for n in numbers}
        self.range_source = {n: "guess" for n in numbers}
        self.range_when: dict[int, str] = {}
        self._range_widgets: list[ttk.Widget] = []
        self.ranges_frame = ttk.Frame(self.frame)
        self.ranges_frame.grid(row=2, column=0, columnspan=4, sticky="w",
                               pady=(4, 0))

        self.fields: dict[str, tk.StringVar] = {}
        self.entries: list[ttk.Widget] = []
        # The unit is part of the label, in the label's own colour: a
        # separate dim unit at the panel's edge was easy to miss.
        rows = (
            ("pixel_mm", "Pixel (mm)"),
            ("pitch_mm", "Row pitch (mm)"),
            ("speed_mm_s", "Speed (mm/s)"),
            ("bias_v", "Bias (V)"),
            ("baseline_s", "Baseline, laser off (s)"),
            ("warmup_s", "Warm-up per laser (s)"),
        )
        grid = ttk.Frame(self.frame)
        grid.grid(row=3, column=0, columnspan=4, sticky="w", pady=(4, 0))
        for i, (key, label) in enumerate(rows):
            r, col = i // 2, (i % 2) * 2
            ttk.Label(grid, text=label).grid(
                row=r, column=col, sticky="w", pady=2,
                padx=(0 if col == 0 else 18, 6))
            text = tk.StringVar(master=app.root, value=getattr(form, key))
            text.trace_add("write", lambda *a: self.changed())
            entry = ttk.Entry(grid, textvariable=text, width=7)
            entry.grid(row=r, column=col + 1, sticky="w")
            self.fields[key] = text
            self.entries.append(entry)

        more = ttk.Frame(self.frame)
        more.grid(row=5, column=0, columnspan=4, sticky="w", pady=(4, 2))
        ttk.Label(more, text="Range if not checked").pack(side="left")
        self.current_range = tk.StringVar(master=app.root,
                                          value=form.current_range)
        combo = ttk.Combobox(more, textvariable=self.current_range,
                             values=list(CURRENT_RANGES), width=6,
                             state="readonly")
        combo.bind("<<ComboboxSelected>>", lambda e: self._default_changed())
        combo.pack(side="left", padx=(6, 0))
        self.entries.append(combo)
        self.serpentine = tk.BooleanVar(master=app.root, value=True)
        serp = ttk.Checkbutton(more, text="serpentine", variable=self.serpentine,
                               command=self.changed)
        serp.pack(side="left", padx=(16, 0))
        self.entries.append(serp)
        self.step_up = tk.BooleanVar(master=app.root, value=True)
        step = ttk.Checkbutton(more, text="step up if clipped",
                               variable=self.step_up, command=self.changed)
        step.pack(side="left", padx=(12, 0))
        self.entries.append(step)

        note = ttk.Frame(self.frame)
        note.grid(row=6, column=0, columnspan=4, sticky="ew", pady=2)
        ttk.Label(note, text="Note", width=13).pack(side="left")
        self.note = tk.StringVar(master=app.root, value="")
        note_entry = ttk.Entry(note, textvariable=self.note)
        note_entry.pack(side="left", fill="x", expand=True)
        self.entries.append(note_entry)

        out = ttk.Frame(self.frame)
        out.grid(row=7, column=0, columnspan=4, sticky="ew", pady=2)
        ttk.Label(out, text="Save runs in", width=13).pack(side="left")
        default = (Path.cwd() / SIM_RUNS) if app.simulated else REAL_RUNS
        self.out = tk.StringVar(master=app.root, value=str(default))
        out_entry = ttk.Entry(out, textvariable=self.out)
        out_entry.pack(side="left", fill="x", expand=True)
        browse = ttk.Button(out, text="...", width=3, command=self.browse)
        browse.pack(side="left", padx=(4, 0))
        self.entries += [out_entry, browse]

        self.plan_label = ttk.Label(self.frame, text="", justify="left",
                                    wraplength=470)
        self.plan_label.grid(row=8, column=0, columnspan=4, sticky="w",
                             pady=(8, 2))
        self.warn_label = ttk.Label(self.frame, text="", justify="left",
                                    style="Warn.TLabel", wraplength=520)
        self.warn_label.grid(row=9, column=0, columnspan=4, sticky="w")
        self.start_btn = ttk.Button(self.frame, text="Start run",
                                    style="Run.TButton",
                                    command=self.start)
        self.start_btn.grid(row=10, column=0, sticky="w", pady=(8, 0))
        self._build_ranges()
        self.frame.columnconfigure(3, weight=1)
        self.replan()

    # ---- the form ----

    def form(self) -> RunForm:
        lasers = tuple(n for n, v in self.laser_vars.items() if v.get())
        f = self.fields
        return RunForm(
            lasers=lasers,
            pixel_mm=f["pixel_mm"].get(), pitch_mm=f["pitch_mm"].get(),
            speed_mm_s=f["speed_mm_s"].get(),
            current_range=self.current_range.get(),
            bias_v=f["bias_v"].get(), baseline_s=f["baseline_s"].get(),
            warmup_s=f["warmup_s"].get(),
            serpentine=self.serpentine.get(),
            allow_unmeasured=self.allow.get(), note=self.note.get(),
            laser_ranges={n: self.range_vars[n].get() for n in lasers},
            range_sources={n: self.range_source[n] for n in lasers},
            step_up=self.step_up.get(),
        )

    # ---- ranges ----

    def _build_ranges(self) -> None:
        """One range per ticked laser, with where it came from."""
        for child in self.ranges_frame.winfo_children():
            child.destroy()
        self._range_widgets = []
        ticked = [n for n, v in self.laser_vars.items() if v.get()]
        ttk.Label(self.ranges_frame, text="Ranges").grid(
            row=0, column=0, sticky="nw", padx=(0, 10))
        if not ticked:
            ttk.Label(self.ranges_frame, text="tick a laser",
                      style="Small.Hint.TLabel").grid(row=0, column=1)
            return
        for i, n in enumerate(ticked):
            cell = ttk.Frame(self.ranges_frame)
            # Two to a line: three ran past the panel's edge.
            cell.grid(row=i // 2, column=1 + i % 2, sticky="w",
                      padx=(0, 14), pady=1)
            ttk.Label(cell, text=f" {n}", compound="left",
                      image=look.swatch(cell, self.app.laser_colour(n),
                                        size=10)).pack(side="left")
            combo = ttk.Combobox(cell, textvariable=self.range_vars[n],
                                 values=list(CURRENT_RANGES), width=5,
                                 state="readonly")
            combo.bind("<<ComboboxSelected>>",
                       functools.partial(self._range_picked, n))
            combo.pack(side="left", padx=(4, 4))
            source = self.range_source[n]
            # When it was checked is in Calibration's step 4.
            text = {"checked": "checked", "set": "set by hand",
                    "guess": "guess"}[source]
            ttk.Label(cell, text=text,
                      style="Accent.TLabel" if source == "checked"
                      else "Small.Hint.TLabel").pack(side="left")
            self._range_widgets.append(combo)
        self.refresh()

    def _range_picked(self, laser: int, event: tk.Event) -> None:
        self._range_set(laser)

    def _range_set(self, laser: int) -> None:
        self.range_source[laser] = "set"
        self._build_ranges()
        self.changed()

    def _default_changed(self) -> None:
        for n, source in self.range_source.items():
            if source == "guess":
                self.range_vars[n].set(self.current_range.get())
        self._build_ranges()
        self.changed()

    def _lasers_changed(self) -> None:
        self._build_ranges()
        self.changed()

    def take_ranges(self, ranges: dict[int, RangeCheck]) -> None:
        """A calibration's checked ranges: they replace guesses and
        earlier checks, not what the operator set by hand after."""
        for n in self.range_vars:
            if n in ranges:
                self.range_vars[n].set(range_name(ranges[n].range_a))
                self.range_source[n] = "checked"
                self.range_when[n] = ranges[n].when[11:16]
            elif self.range_source[n] == "checked":
                self.range_source[n] = "guess"
                self.range_vars[n].set(self.current_range.get())
        self._build_ranges()
        self.changed()

    def changed(self) -> None:
        """Re-plan shortly: once typing pauses, not on every key. The
        Plan tab comes to the front, to show what the change does."""
        self._show_plan_tab = True
        if self._after is not None:
            self.app.root.after_cancel(self._after)
        self._after = self.app.root.after(PLAN_DELAY_MS, self.replan)

    def replan(self) -> None:
        self._after = None
        self._unmeasured_boxes()
        try:
            self.plan = plan_form(self.form(), self.app.calibration(),
                                  self.app.machine,
                                  simulated=self.app.simulated)
        except FormError as exc:
            self.plan = None
            error = str(exc)
            self.plan_label.configure(text=error, style="Bad.TLabel")
            self.warn_label.configure(text="")
        else:
            error = ""
            self.plan_label.configure(
                text=f"{self.plan.lines[-1]}; the Plan tab shows the sweep "
                     "and each laser's time", style="TLabel")
            self.warn_label.configure(text="\n".join(self.plan.warnings))
        run_panel = getattr(self.app, "run_panel", None)
        if run_panel is not None:
            run_panel.plan_view.show(self.plan, error)
            if self._show_plan_tab and self.app.state is not State.RUNNING:
                run_panel.notebook.select(run_panel.plan_view.frame)
        self._show_plan_tab = False
        self.refresh()

    def _unmeasured_boxes(self) -> None:
        allowed = self.allow.get()
        for laser in self.app.machine.lasers:
            if laser.measured:
                continue
            box = self.laser_boxes[laser.number]
            if not allowed:
                self.laser_vars[laser.number].set(False)
            _enable(box, allowed and self.app.state is not State.RUNNING)

    def browse(self) -> None:
        path = filedialog.askdirectory(parent=self.app.root,
                                       title="Save runs in",
                                       initialdir=self.out.get())
        if path:
            self.out.set(path)

    # ---- Start ----

    def start(self) -> None:
        self.replan()
        plan = self.plan
        if plan is None:
            return
        guessed = plan.guessed()
        if guessed:
            # D25: offer the check for lasers whose range is a guess.
            frame = plan.plans[0].placement.frame
            named = ", ".join(str(n) for n in guessed)
            answer = messagebox.askyesnocancel(
                "Check ranges first?",
                f"The current range of laser(s) {named} has not been "
                "checked on this sample: it is a guess.\n\n"
                f"Yes: check them now (about "
                f"{eta(check_duration_s(frame, len(guessed)))}; the stage "
                "moves and the lasers come on), then press Start run "
                "again.\n"
                "No: start anyway"
                + (" (a laser that clips starts again one range up)."
                   if plan.request.step_up else
                   " (the step-up is off: a clip ends the run).")
                + "\nCancel: neither.",
                parent=self.app.root,
            )
            if answer is None:
                return
            if answer:
                self.app.calibration_panel.check_ranges(guessed)
                return
        out = Path(self.out.get()).expanduser()
        lasers = ", ".join(str(p.laser) for p in plan.plans)
        text = "\n".join((
            *plan.lines, *plan.warnings, "",
            f"Lasers {lasers}. The stage will home first and the lasers "
            "will come on.",
            f"Files go to {out}.",
        ))
        if not messagebox.askokcancel("Start the run?", text,
                                      parent=self.app.root):
            return
        from multilbic.bench.report import provenance

        if not self.app.worker.start_run(plan.request, out, provenance()):
            self.app.refused("start run")

    # ---- redrawing ----

    def handle(self, event: Event) -> None:
        if isinstance(event, CalibrationChanged):
            known = {n: r.when for n, r in event.ranges.items()}
            mine = {n: self.range_when.get(n) for n in self.range_source
                    if self.range_source[n] == "checked"}
            if {n: w[11:16] for n, w in known.items()} != mine:
                self.take_ranges(event.ranges)

    def refresh(self) -> None:
        state = self.app.state
        editable = state is not State.RUNNING
        for widget in self.entries:
            _enable(widget, editable)
        for n, box in self.laser_boxes.items():
            if self.app.machine.laser(n).measured:
                _enable(box, editable)
        _enable(self.allow_box, editable)
        for combo in self._range_widgets:
            _enable(combo, editable)
        _enable(self.start_btn, state is State.IDLE and self.plan is not None)


def _ranges_text(ranges: dict[int, RangeCheck]) -> str:
    if not ranges:
        return ("not checked: each laser ticked in Run setup, on a grid "
                "over the sample")
    when = max(r.when for r in ranges.values())[11:16]
    listed = ", ".join(f"{n}: {range_name(r.range_a)}"
                       for n, r in sorted(ranges.items()))
    return f"{listed} (checked {when} UTC)"


def _cal_dir() -> Path:
    for path in CAL_DIRS:
        if path.is_dir():
            return path
    return Path.home()


def _enable(widget: ttk.Widget, on: bool) -> None:
    widget.state(["!disabled"] if on else ["disabled"])

