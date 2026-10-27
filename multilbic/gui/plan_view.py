"""
The Plan tab: what a run would do, drawn and timed, before it starts.

It follows the run setup as it is typed (`RunSetupPanel.replan`):

* **the sweep** - the sample as a run places it, turned as the operator
  sees the stage (`[display]`), with the rows the spot will scan: their
  direction, the run-up and run-out off the sample (dashed), where the
  run starts. Too many rows to draw, and every n-th is drawn, saying so;
* **close-ups**, one per laser, at true scale: a few rows at the pitch
  with the laser's spot on them (`spot_um` in machine.toml), and the
  pixels along a row - whether rows overlap, touch or leave gaps;
* **the times** - each laser's, homing and the whole run's, and the
  clock time each would be done by if started now (`estimate_run`);
* **notes** in plain words (`runform`'s `RunPlan.notes`).
"""

from __future__ import annotations

import datetime
import math
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from multilbic.gui import look
from multilbic.gui.runform import RunPlan, eta

if TYPE_CHECKING:
    from multilbic.gui.app import App

#: Screen direction of each `[display]` word, canvas y pointing down.
VECTORS = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}
#: Drawn rows are at least this far apart; more rows, and every n-th.
MIN_ROW_PX = 7
CLOSEUP_PX = (170, 100)
CLOCK_MS = 30_000


class PlanView:
    def __init__(self, app: App, notebook: ttk.Notebook):
        self.app = app
        self.frame = ttk.Frame(notebook, padding=6)
        notebook.add(self.frame, text="Plan")
        self.plan: RunPlan | None = None
        self.error = ""
        self._clock_id: str | None = None

        self.headline = ttk.Label(self.frame, text="", style="Bold.TLabel")
        self.headline.pack(anchor="w")
        self.canvas = tk.Canvas(self.frame, height=260, highlightthickness=0,
                                borderwidth=0)
        self.canvas.pack(fill="both", expand=True, pady=(6, 6))
        self.canvas.bind("<Configure>", lambda e: self._draw_sweep())

        self.closeups = ttk.Frame(self.frame)
        self.closeups.pack(fill="x")
        self.table = ttk.Frame(self.frame)
        self.table.pack(fill="x", pady=(8, 4))
        self.notes = ttk.Label(self.frame, text="", justify="left",
                               style="Hint.TLabel", wraplength=740)
        self.notes.pack(anchor="w", fill="x")
        app.theme.on_change(lambda t: self.render(), widget=self.frame)

    # ---- what the run setup calls ----

    def show(self, plan: RunPlan | None, error: str = "") -> None:
        self.plan, self.error = plan, error
        self.render()

    def render(self) -> None:
        self._draw_sweep()
        self._draw_closeups()
        self._fill_table()
        plan = self.plan
        if plan is None:
            self.headline.configure(
                text=self.error or "Set a calibration and the run's options "
                "to see the plan")
            self.notes.configure(text="")
        else:
            done = datetime.datetime.now() + datetime.timedelta(
                seconds=plan.estimate_s)
            lasers = len(plan.plans)
            self.headline.configure(
                text=f"{lasers} laser{'s' if lasers > 1 else ''}, about "
                     f"{eta(plan.estimate_s)} in all; done by about "
                     f"{done:%H:%M} if started now")
            self.notes.configure(text="\n".join(f"- {n}" for n in plan.notes))
        if self._clock_id is not None:
            self.app.root.after_cancel(self._clock_id)
        # "Done by" moves on with the clock.
        self._clock_id = self.app.root.after(CLOCK_MS, self._tick)

    def _tick(self) -> None:
        self._clock_id = None
        if self.plan is not None:
            self.render()

    # ---- the sweep ----

    def _draw_sweep(self) -> None:
        c = self.canvas
        theme = self.app.theme
        pal = theme.palette
        c.configure(background=pal.field)
        c.delete("all")
        plan = self.plan
        width = max(c.winfo_width(), 50)
        height = max(c.winfo_height(), 50)
        if plan is None:
            c.create_text(width / 2, height / 2, fill=pal.muted,
                          text="the sweep shows here", font="SMUCanvas")
            return
        first = plan.plans[0]
        frame = first.placement.frame
        rows = first.raster.rows
        a0, b0 = frame.origin_ab_mm
        u_lo = min(min(r.a_from_mm, r.a_to_mm) for r in rows) - a0
        u_hi = max(max(r.a_from_mm, r.a_to_mm) for r in rows) - a0
        v_lo, v_hi = 0.0, frame.height_mm
        d = self.app.machine.display
        ux, uy = VECTORS[d.u_points]
        vx, vy = VECTORS[d.v_points]
        horizontal_u = ux != 0
        span_x = (u_hi - u_lo) if horizontal_u else (v_hi - v_lo)
        span_y = (v_hi - v_lo) if horizontal_u else (u_hi - u_lo)
        margin = 36
        scale = min((width - 2 * margin) / max(span_x, 1e-6),
                    (height - 2 * margin) / max(span_y, 1e-6))
        cu, cv = (u_lo + u_hi) / 2, (v_lo + v_hi) / 2

        def at(u: float, v: float) -> tuple[float, float]:
            return (width / 2 + ((u - cu) * ux + (v - cv) * vx) * scale,
                    height / 2 + ((u - cu) * uy + (v - cv) * vy) * scale)

        # The sample.
        corners = [at(0, 0), at(frame.width_mm, 0),
                   at(frame.width_mm, frame.height_mm), at(0, frame.height_mm)]
        c.create_polygon(*[p for xy in corners for p in xy],
                         fill=look.blend_soft(theme), outline=theme.accent,
                         width=1)
        # The rows: every n-th if they are too close to draw.
        pitch_px = first.raster.request.pitch_mm * scale
        step = max(1, math.ceil(MIN_ROW_PX / max(pitch_px, 1e-6)))
        shown = [r for r in rows if r.index % step == 0]
        if rows[-1] not in shown:
            shown.append(rows[-1])
        ink = theme.accent
        for k, row in enumerate(shown):
            v = row.b_mm - b0
            u_from, u_to = row.a_from_mm - a0, row.a_to_mm - a0
            # Run-up and run-out, off the sample: dashed.
            c.create_line(*at(u_from, v), *at(u_to, v), fill=pal.muted,
                          dash=(3, 3))
            lo, hi = sorted((0.0, frame.width_mm))
            inside = (max(min(u_from, u_to), lo), min(max(u_from, u_to), hi))
            start, end = (inside if u_to > u_from else inside[::-1])
            c.create_line(*at(start, v), *at(end, v), fill=ink, width=2,
                          arrow="last", arrowshape=(8, 9, 3))
            if step == 1 and k + 1 < len(shown):
                nxt = shown[k + 1]
                c.create_line(*at(u_to, v), *at(nxt.a_from_mm - a0,
                                                 nxt.b_mm - b0),
                              fill=pal.muted)
        # Where it starts, and the corner.
        r0 = rows[0]
        x, y = at(r0.a_from_mm - a0, r0.b_mm - b0)
        c.create_oval(x - 5, y - 5, x + 5, y + 5, fill=pal.good, outline="")
        c.create_text(x, y - 12, text="start", fill=pal.ink2, font="SMUCanvas")
        x, y = at(0, 0)
        c.create_oval(x - 3, y - 3, x + 3, y + 3, fill=theme.accent,
                      outline="")
        # The first laser's spot, at true scale, where the first row
        # enters the sample.
        spot = self.app.machine.laser(first.laser).spot_um
        if spot is not None and spot / 1000 * scale >= 2:
            sx, sy = at(0 if r0.a_to_mm > r0.a_from_mm else frame.width_mm,
                        r0.b_mm - b0)
            rad = spot / 2000 * scale
            c.create_oval(sx - rad, sy - rad, sx + rad, sy + rad,
                          outline=self.app.laser_colour(first.laser), width=2)
        legend = (f"{len(rows)} rows, every {step}{_nth(step)} drawn"
                  if step > 1 else f"{len(rows)} rows")
        c.create_text(
            8, height - 8, anchor="sw", fill=pal.muted, font="SMUSmall",
            text=f"{legend}; dashed: run-up and run-out, off the sample; "
                 "green: where it starts",
        )
        bar = _round_length(span_x / 5)
        x1, y1 = width - 12, height - 10
        c.create_line(x1 - bar * scale, y1, x1, y1, fill=pal.ink2, width=2)
        c.create_text(x1 - bar * scale / 2, y1 - 4, anchor="s",
                      fill=pal.ink2, font="SMUSmall", text=f"{bar:g} mm")

    # ---- close-ups ----

    def _draw_closeups(self) -> None:
        for child in self.closeups.winfo_children():
            child.destroy()
        plan = self.plan
        if plan is None:
            return
        theme = self.app.theme
        pal = theme.palette
        request = plan.request
        pitch = request.pitch_mm * 1000
        pixel = request.pixel_mm * 1000
        spots = [self.app.machine.laser(p.laser).spot_um or 0.0
                 for p in plan.plans]
        # One window, and so one scale, for all: spots compare at a glance.
        window_um = max(3.5 * pitch, 2.5 * max(spots), 8 * pixel)
        w, h = CLOSEUP_PX
        k = min(w, h) / window_um
        bar = _round_length(window_um / 4000) * 1000
        ttk.Label(self.closeups, style="Hint.TLabel", justify="left",
                  text=f"Close-up,\ntrue scale:\nbar {bar:g} µm") \
            .pack(side="left", anchor="n", padx=(0, 8))
        for p in plan.plans:
            laser = self.app.machine.laser(p.laser)
            colour = self.app.laser_colour(p.laser)
            spot = laser.spot_um
            box = ttk.Frame(self.closeups)
            box.pack(side="left", padx=(0, 10))
            c = tk.Canvas(box, width=w, height=h, highlightthickness=0,
                          borderwidth=0, background=pal.field)
            c.pack()
            c.create_line(6, h - 6, 6 + bar * k, h - 6, fill=pal.ink2,
                          width=2)
            cy = h / 2
            for n in (-2, -1, 0, 1, 2):
                y = cy + n * pitch * k
                if 0 <= y <= h:
                    c.create_line(0, y, w, y, fill=pal.muted)
                    if spot is not None:
                        r = spot / 2 * k
                        c.create_oval(w / 2 - r, y - r, w / 2 + r, y + r,
                                      outline=colour, width=2)
            # Pixels along the middle row, if they are big enough to see.
            if pixel * k >= 3:
                x = w / 2 - math.floor(w / 2 / (pixel * k)) * pixel * k
                while x <= w:
                    c.create_line(x, cy - 3, x, cy + 3, fill=pal.ink2)
                    x += pixel * k
            if spot is None:
                c.create_text(w / 2, cy, text="spot not measured",
                              fill=pal.muted, font="SMUSmall")
            ttk.Label(box, image=look.swatch(box, colour, 10),
                      compound="left", style="Small.Hint.TLabel",
                      text=f" laser {p.laser}: spot "
                      + (f"{spot:g} µm" if spot else "?")
                      + f", rows {pitch:g} µm").pack(anchor="w")

    # ---- the times ----

    def _fill_table(self) -> None:
        for child in self.table.winfo_children():
            child.destroy()
        plan = self.plan
        if plan is None:
            return
        heads = ("", "Rows", "Each row", "Warm-up", "Time", "Done by")
        for col, text in enumerate(heads):
            ttk.Label(self.table, text=text, style="Hint.TLabel").grid(
                row=0, column=col, sticky="w", padx=(0, 18))
        now = datetime.datetime.now()
        elapsed = plan.estimate.homing_s
        self._row(1, "Homing", "", "", "",
                  eta(plan.estimate.homing_s), now, elapsed)
        for i, (p, e) in enumerate(zip(plan.plans, plan.estimate.lasers,
                                       strict=True)):
            elapsed += e.total_s
            each = p.raster.estimate_s / max(1, len(p.raster.rows))
            self._row(2 + i, f"Laser {p.laser} ({p.wavelength_nm} nm)",
                      str(len(p.raster.rows)), f"{each:.1f} s",
                      eta(e.warmup_s) if e.warmup_s else "-",
                      eta(e.total_s), now, elapsed,
                      colour=self.app.laser_colour(p.laser))
        r = 2 + len(plan.plans)
        ttk.Label(self.table, text="Whole run", style="Bold.TLabel").grid(
            row=r, column=0, sticky="w", pady=(4, 0))
        ttk.Label(self.table, text=eta(plan.estimate_s),
                  style="Bold.TLabel").grid(row=r, column=4, sticky="w",
                                            pady=(4, 0))
        done = now + datetime.timedelta(seconds=plan.estimate_s)
        ttk.Label(self.table, text=f"{done:%H:%M}", style="Bold.TLabel") \
            .grid(row=r, column=5, sticky="w", pady=(4, 0))

    def _row(self, r: int, name: str, rows: str, each: str, warmup: str,
             time: str, now: datetime.datetime, elapsed: float,
             colour: str | None = None) -> None:
        label = ttk.Label(self.table, text=f" {name}" if colour else name)
        if colour:
            label.configure(image=look.swatch(self.table, colour, 10),
                            compound="left")
        label.grid(row=r, column=0, sticky="w", padx=(0, 18))
        done = now + datetime.timedelta(seconds=elapsed)
        for col, text in enumerate((rows, each, warmup, time,
                                    f"{done:%H:%M}"), start=1):
            ttk.Label(self.table, text=text).grid(
                row=r, column=col, sticky="w", padx=(0, 18))


def _nth(n: int) -> str:
    return "nd" if n % 10 == 2 and n % 100 != 12 else \
        "rd" if n % 10 == 3 and n % 100 != 13 else "th"


def _round_length(target: float) -> float:
    for length in (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20):
        if length >= target:
            return float(length)
    return 20.0
