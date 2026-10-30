"""
Focus assist in the window (Phase 6 step 6, D24): a small window of its
own, opened from the Lasers panel's Focus button, beside the main one.

Pick the laser and the edges, Start: the stage homes, brings the
photodiode under the laser and passes back and forth across the edge
while the focus is turned at the laser. Each pass shows its 10-90 %
width big, the best so far, and the mean and scatter of the last few,
and adds a point to the trace below. Done measures the laser again and
shows what it would change in machine.toml; Save writes it. Esc or Stop
in the main window stops at once.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from multilbic.gui.worker import (
    Event,
    FocusEnded,
    FocusPassed,
    FocusStarted,
    MachineChanged,
    State,
    StateChanged,
)
from multilbic.run.focus import RECENT, FocusPass, FocusRequest

if TYPE_CHECKING:
    from multilbic.gui.app import App

TRACE_W, TRACE_H = 460, 180
#: The trace shows this many passes at most, the latest on the right.
TRACE_PASSES = 60

EDGES = (((0,), "A: the blade at the sample's height"),
         ((0, 1), "A and B: astigmatism too"))


class FocusWindow:
    def __init__(self, app: App):
        self.app = app
        top = tk.Toplevel(app.root)
        self.top = top
        top.title("Focus assist")
        top.transient(app.root)
        top.protocol("WM_DELETE_WINDOW", self.close)
        top.bind("<Escape>", lambda e: app.stop())
        body = ttk.Frame(top, padding=12)
        body.pack(fill="both", expand=True)

        choose = ttk.Frame(body)
        choose.pack(fill="x")
        ttk.Label(choose, text="Laser").grid(row=0, column=0, sticky="w")
        self.laser = tk.IntVar(master=top, value=app.lasers.lit or 1)
        lasers = ttk.Frame(choose)
        lasers.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.choosers: list[ttk.Radiobutton] = []
        for n in app.laser_numbers():
            rb = ttk.Radiobutton(lasers, text=str(n), value=n,
                                 variable=self.laser)
            rb.pack(side="left", padx=(0, 6))
            self.choosers.append(rb)
        ttk.Label(choose, text="Edges").grid(row=1, column=0, sticky="w",
                                             pady=(4, 0))
        self.edges = tk.IntVar(master=top, value=0)
        edges = ttk.Frame(choose)
        edges.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(4, 0))
        for i, (_, text) in enumerate(EDGES):
            rb = ttk.Radiobutton(edges, text=text, value=i,
                                 variable=self.edges)
            rb.pack(anchor="w")
            self.choosers.append(rb)

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(10, 0))
        self.start_btn = ttk.Button(buttons, text="Start", command=self.start)
        self.start_btn.pack(side="left")
        self.done_btn = ttk.Button(buttons, text="Done: measure",
                                   command=self.done)
        self.done_btn.pack(side="left", padx=(6, 0))
        self.save_btn = ttk.Button(buttons, text="Save to machine.toml",
                                   command=self.save)
        self.save_btn.pack(side="left", padx=(6, 0))
        ttk.Label(
            body, style="Small.Hint.TLabel", wraplength=460, justify="left",
            text="Start homes and moves the stage to the photodiode, then "
                 "lights the laser. The stage then moves only about a "
                 "millimetre round the edge. Esc stops at once.",
        ).pack(anchor="w", pady=(6, 0))

        readout = ttk.Frame(body)
        readout.pack(fill="x", pady=(10, 0))
        # Fixed widths: a new pass's numbers don't resize the window.
        self.width = ttk.Label(readout, text="-", style="Position.TLabel",
                               width=20, anchor="w")
        self.width.pack(anchor="w")
        self.detail = ttk.Label(readout, text="", style="Hint.TLabel",
                                width=64, anchor="w")
        self.detail.pack(anchor="w")

        self.canvas = tk.Canvas(body, width=TRACE_W, height=TRACE_H,
                                highlightthickness=0, borderwidth=0)
        self.canvas.pack(fill="x", pady=(8, 0))
        self.summary = ttk.Label(body, text="", justify="left",
                                 wraplength=460)
        self.summary.pack(anchor="w", pady=(8, 0))

        self.passes: list[FocusPass] = []
        self.can_save = False
        app.theme.on_change(lambda t: self.draw(), widget=self.canvas)
        self.draw()
        self.refresh()

    # ---- actions ----

    def start(self) -> None:
        axes, _ = EDGES[self.edges.get()]
        if not self.app.worker.start_focus(
                FocusRequest(self.laser.get(), axes=axes)):
            self.app.refused("focus")

    def done(self) -> None:
        if self.app.worker.finish_focus():
            self.detail.configure(text="Done: this pass, then measuring the "
                                       "laser again")

    def save(self) -> None:
        if not self.app.worker.save_focus():
            self.app.refused("save")

    def close(self) -> None:
        if self.app.state is State.FOCUSING:
            self.app.stop()
        self.app.focus_window = None
        self.top.destroy()

    # ---- events ----

    def handle(self, event: Event) -> None:
        if isinstance(event, FocusStarted):
            self.passes = []
            self.can_save = False
            self.width.configure(text="finding the edge...")
            self.detail.configure(text="")
            self.summary.configure(text="")
            self.draw()
        elif isinstance(event, FocusPassed):
            p = event.focus_pass
            self.passes.append(p)
            self.show(p)
            self.draw()
        elif isinstance(event, FocusEnded):
            if event.result is None:
                self.summary.configure(text=f"ended: {event.error}")
            else:
                lines = event.result.lines(self.app.machine)
                if event.error:
                    lines.append(f"nothing to save: {event.error}")
                self.summary.configure(text="\n".join(lines))
            self.can_save = (event.result is not None
                             and event.result.proposal is not None
                             and not event.error)
        elif isinstance(event, MachineChanged):
            self.can_save = False
            self.summary.configure(
                text=self.summary.cget("text") + f"\nsaved: {event.path}")
        if isinstance(event, (StateChanged, FocusEnded, MachineChanged)):
            self.refresh()

    def show(self, p: FocusPass) -> None:
        if p.width_mm is None:
            self.detail.configure(text=f"pass {p.number}: no edge "
                                       f"({p.error})")
            return
        edge = "A" if p.axis == 0 else "B"
        self.width.configure(text=f"{p.width_mm * 1000:.1f} µm  ({edge})")
        text = f"best {p.best_mm * 1000:.1f} µm"  # type: ignore[operator]
        if p.recent_mm is not None and p.scatter_mm is not None:
            text += (f"   last {RECENT}: {p.recent_mm * 1000:.1f} ± "
                     f"{p.scatter_mm * 1000:.1f} µm")
        self.detail.configure(text=f"pass {p.number}: {text}")

    def refresh(self) -> None:
        state = self.app.state
        idle = state is State.IDLE
        _enable(self.start_btn, idle)
        _enable(self.done_btn, state is State.FOCUSING)
        _enable(self.save_btn, idle and self.can_save)
        for rb in self.choosers:
            _enable(rb, idle)

    # ---- the trace ----

    def draw(self) -> None:
        c = self.canvas
        theme = self.app.theme
        pal = theme.palette
        c.configure(background=pal.field)
        c.delete("all")
        good = [p for p in self.passes[-TRACE_PASSES:] if p.width_mm]
        w = max(c.winfo_width(), TRACE_W)
        h = TRACE_H
        if not good:
            c.create_text(w / 2, h / 2, fill=pal.muted, font="SMUCanvas",
                          text="each pass's width shows here")
            return
        widths = [p.width_mm * 1000 for p in good]  # type: ignore[operator]
        top = max(widths) * 1.1
        left, right, pad = 44, w - 10, 14
        first = good[0].number
        span = max(good[-1].number - first, 1)

        def xy(p: FocusPass) -> tuple[float, float]:
            x = left + (right - left) * (p.number - first) / span
            y = h - pad - (h - 2 * pad) * (p.width_mm * 1000) / top  # type: ignore[operator]
            return x, y

        for frac in (0.0, 0.5, 1.0):
            y = h - pad - (h - 2 * pad) * frac
            c.create_line(left, y, right, y, fill=pal.rule)
            c.create_text(left - 6, y, anchor="e", fill=pal.muted,
                          font="SMUCanvas", text=f"{top * frac:.0f}")
        c.create_text(left, 2, anchor="nw", fill=pal.muted, font="SMUCanvas",
                      text="10-90 % width, µm")
        best = min(widths)
        y = h - pad - (h - 2 * pad) * best / top
        c.create_line(left, y, right, y, fill=theme.accent, dash=(4, 3))
        for axis, colour in ((0, theme.accent), (1, pal.muted)):
            points = [xy(p) for p in good if p.axis == axis]
            if len(points) > 1:
                c.create_line(*[v for pt in points for v in pt],
                              fill=colour, width=2)
            for x, y in points:
                c.create_oval(x - 3, y - 3, x + 3, y + 3, fill=colour,
                              outline="")


def _enable(widget: ttk.Widget, on: bool) -> None:
    widget.state(["!disabled"] if on else ["disabled"])
