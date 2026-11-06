"""
The Maintenance window: what keeps the lasers where machine.toml says,
done from the window rather than the command line. Opened from the
Lasers panel's Maintenance button, beside the main window.

* **Focus**: focus assist on the photodiode (`gui.focus_window`).
* **Photodiode**: commissioning, `multilbic commission`: each chosen
  laser found on the photodiode, its position and spot, and what that
  would change in machine.toml. After any work in the box (lasers move
  when handled), and after refocusing.
* **Line-up**: a short run of the chosen lasers over a cell's corner,
  placed from the photodiode, then each laser's offset on the cell
  against the reference laser (`run.lineup`), and what that would
  change. Its maps show in the run column like any run's.

Each tab shows what it found and saves it only when asked. Esc, or Stop
in the main window, stops whatever is running at once.
"""

from __future__ import annotations

import dataclasses
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from multilbic.gui.focus_window import FocusTab
from multilbic.gui.runform import FormError, plan_form
from multilbic.gui.worker import (
    CalibrationChanged,
    CommissionEnded,
    Event,
    LineUpEnded,
    MachineChanged,
    State,
    StateChanged,
)
from multilbic.run import lineup as lu
from multilbic.run.commission import CommissionRequest, estimate_s
from multilbic.run.session import duration

if TYPE_CHECKING:
    from multilbic.gui.app import App

TEXT_W = 74
#: Shown in the tabs while something of theirs runs.
INFRARED_NOTE = ("Lasers 5 and 6 are infrared: close the box before "
                 "starting.")


class MaintenanceWindow:
    def __init__(self, app: App):
        self.app = app
        top = tk.Toplevel(app.root)
        self.top = top
        top.title("Maintenance")
        top.transient(app.root)
        top.protocol("WM_DELETE_WINDOW", self.close)
        top.bind("<Escape>", lambda e: app.stop())
        self.notebook = ttk.Notebook(top)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)
        self.focus = FocusTab(app, self.notebook)
        self.commission = CommissionTab(app, self.notebook)
        self.lineup = LineUpTab(app, self.notebook)
        for tab, title in ((self.focus, "Focus"),
                           (self.commission, "Photodiode"),
                           (self.lineup, "Line-up")):
            self.notebook.add(tab.frame, text=title)

    def handle(self, event: Event) -> None:
        for tab in (self.focus, self.commission, self.lineup):
            tab.handle(event)

    def refresh(self) -> None:
        for tab in (self.focus, self.commission, self.lineup):
            tab.refresh()

    def close(self) -> None:
        if self.app.state in (State.FOCUSING, State.COMMISSIONING):
            self.app.stop()
        self.app.maintenance = None
        self.top.destroy()


def _laser_checks(app: App, parent: tk.Misc,
                  master: tk.Misc) -> dict[int, tk.BooleanVar]:
    frame = ttk.Frame(parent)
    frame.pack(anchor="w")
    ttk.Label(frame, text="Lasers").pack(side="left")
    out: dict[int, tk.BooleanVar] = {}
    for n in app.laser_numbers():
        var = tk.BooleanVar(master=master, value=True)
        ttk.Checkbutton(frame, text=str(n), variable=var).pack(
            side="left", padx=(8, 0))
        out[n] = var
    return out


def _text(parent: tk.Misc, height: int) -> tk.Text:
    box = tk.Text(parent, width=TEXT_W, height=height, wrap="word",
                  borderwidth=0, highlightthickness=0)
    box.configure(state="disabled")
    return box


def _show(box: tk.Text, lines: list[str]) -> None:
    box.configure(state="normal")
    box.delete("1.0", "end")
    box.insert("end", "\n".join(lines))
    box.configure(state="disabled")


def _out_folder(app: App) -> Path:
    return Path(app.setup.out.get()).expanduser()


class CommissionTab:
    """`multilbic commission` from the window."""

    def __init__(self, app: App, parent: tk.Misc):
        self.app = app
        body = ttk.Frame(parent, padding=12)
        self.frame = body
        ttk.Label(
            body, wraplength=520, justify="left",
            text="Finds each laser on the photodiode: where it lands and "
                 "how big its spot is, and what that changes in "
                 "machine.toml. After any work in the box, and after "
                 "refocusing.").pack(anchor="w")
        self.lasers = _laser_checks(app, body, body)
        self.new_corner = tk.BooleanVar(master=body, value=False)
        ttk.Checkbutton(
            body, variable=self.new_corner,
            text="The photodiode was moved: measure its corner again "
                 f"(with laser {app.machine.geometry.reference_laser}, "
                 "the reference)").pack(anchor="w", pady=(4, 0))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(10, 0))
        self.start_btn = ttk.Button(buttons, text="Start", command=self.start)
        self.start_btn.pack(side="left")
        self.save_btn = ttk.Button(buttons, text="Save to machine.toml",
                                   command=self.save)
        self.save_btn.pack(side="left", padx=(6, 0))
        self.estimate = ttk.Label(buttons, text="", style="Hint.TLabel")
        self.estimate.pack(side="left", padx=(10, 0))
        ttk.Label(body, style="Small.Hint.TLabel", wraplength=520,
                  justify="left",
                  text="Start homes, then takes the photodiode under each "
                       "laser in turn and lights it. " + INFRARED_NOTE
                  ).pack(anchor="w", pady=(6, 0))
        self.result = _text(body, 16)
        self.result.pack(fill="both", expand=True, pady=(10, 0))
        self.can_save = False
        for var in self.lasers.values():
            var.trace_add("write", lambda *_: self._estimate())
        self._estimate()
        self.refresh()

    def chosen(self) -> tuple[int, ...]:
        return tuple(n for n, v in self.lasers.items() if v.get())

    def request(self) -> CommissionRequest:
        return CommissionRequest(self.chosen(), new_corner=self.new_corner.get())

    def _estimate(self) -> None:
        lasers = self.chosen()
        self.estimate.configure(
            text=f"about {duration(estimate_s(self.request(), lasers))}"
            if lasers else "choose a laser")

    def start(self) -> None:
        lasers = self.chosen()
        if not lasers:
            self.app.status("commission: choose a laser", error=True)
            return
        if self.app.machine.photodiode is None:
            self.app.status("commission: machine.toml has no [photodiode]",
                            error=True)
            return
        named = ", ".join(map(str, lasers))
        if not messagebox.askokcancel(
                "Commission on the photodiode?",
                f"Lasers {named}, about "
                f"{duration(estimate_s(self.request(), lasers))}.\n\n"
                "The stage homes, then goes to the photodiode under each "
                "laser, which comes on.\n" + INFRARED_NOTE,
                parent=self.frame):
            return
        from multilbic.bench.report import provenance

        if not self.app.worker.start_commission(
                self.request(), _out_folder(self.app), provenance()):
            self.app.refused("commission")
            return
        _show(self.result, ["commissioning..."])

    def save(self) -> None:
        if not self.app.worker.save_commission():
            self.app.refused("save")

    def handle(self, event: Event) -> None:
        if isinstance(event, CommissionEnded):
            lines: list[str] = []
            if event.result is not None:
                lines = event.result.lines(self.app.machine)
            if event.report is not None:
                lines.append(f"report: {event.report}")
            self.can_save = (event.result is not None
                             and event.result.proposal is not None
                             and not event.error)
            if event.error and not self.can_save:
                lines.append(f"nothing to save: {event.error}")
            _show(self.result, lines)
        elif isinstance(event, MachineChanged) and self.can_save:
            self.can_save = False
            self.result.configure(state="normal")
            self.result.insert("end", f"\nsaved: {event.path}")
            self.result.configure(state="disabled")
        if isinstance(event, (StateChanged, CommissionEnded, MachineChanged)):
            self.refresh()

    def refresh(self) -> None:
        idle = self.app.state is State.IDLE
        _enable(self.start_btn, idle)
        _enable(self.save_btn, idle and self.can_save)


class LineUpTab:
    """A run over a cell's corner, and each laser's offset on the cell."""

    COLUMNS = (("laser", "Laser", 50), ("u", "Edge u, mm", 100),
               ("v", "Edge v, mm", 100), ("shift", "Row shift", 80),
               ("offset", "Offset, µm (X, Y)", 140))

    def __init__(self, app: App, parent: tk.Misc):
        self.app = app
        body = ttk.Frame(parent, padding=12)
        self.frame = body
        ref = app.machine.geometry.reference_laser
        ttk.Label(
            body, wraplength=520, justify="left",
            text="Where each laser really lands on a cell, against laser "
                 f"{ref}, the reference: each beam meets the photodiode's "
                 "blades a little above the cell, at its own angle. Set the "
                 f"calibration's corner on a cell's corner under laser {ref} "
                 f"first; the run maps a {lu.PATCH_MM:g} mm square centred on "
                 "it, every laser placed from the photodiode.").pack(
            anchor="w")
        self.calibration = ttk.Label(body, text="", style="Hint.TLabel",
                                     wraplength=520, justify="left")
        self.calibration.pack(anchor="w", pady=(6, 0))
        self.lasers = _laser_checks(app, body, body)
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(10, 0))
        self.start_btn = ttk.Button(buttons, text="Start", command=self.start)
        self.start_btn.pack(side="left")
        self.save_btn = ttk.Button(buttons, text="Save offsets to "
                                   "machine.toml", command=self.save)
        self.save_btn.pack(side="left", padx=(6, 0))
        ttk.Label(body, style="Small.Hint.TLabel", wraplength=520,
                  justify="left",
                  text="Each laser's current range is the run setup's. "
                       + INFRARED_NOTE).pack(anchor="w", pady=(6, 0))
        self.table = ttk.Treeview(body, columns=[c for c, _, _ in
                                                 self.COLUMNS],
                                  show="headings", height=6)
        for key, title, width in self.COLUMNS:
            self.table.heading(key, text=title)
            self.table.column(key, width=width, anchor="center")
        self.table.pack(fill="x", pady=(10, 0))
        self.summary = _text(body, 6)
        self.summary.pack(fill="both", expand=True, pady=(8, 0))
        self.can_save = False
        self._show_calibration()
        self.refresh()

    def chosen(self) -> tuple[int, ...]:
        return tuple(n for n, v in self.lasers.items() if v.get())

    def _show_calibration(self) -> None:
        cal = self.app.calibration()
        if cal is None:
            text = ("No calibration yet: set the corner (on a cell's corner) "
                    "in the Calibration panel, or load one.")
        else:
            a, b = cal.corner_ab_mm
            text = (f"Corner: {cal.sample}, A {a:.3f} B {b:.3f} "
                    f"(made under laser {cal.reference_laser})")
        self.calibration.configure(text=text)

    def plan(self):  # noqa: ANN201 - a RunPlan, or None with the reason shown
        cal = self.app.calibration()
        if cal is None:
            self.app.status("line-up: no calibration yet", error=True)
            return None
        lasers = self.chosen()
        form = dataclasses.replace(
            self.app.setup.form(), lasers=lasers,
            pixel_mm=f"{lu.PIXEL_MM:g}", pitch_mm=f"{lu.PITCH_MM:g}",
            speed_mm_s=f"{lu.SPEED_MM_S:g}", serpentine=True, locate=True,
            note="line-up",
            laser_ranges={n: self.app.setup.range_vars[n].get()
                          for n in lasers},
            range_sources={n: self.app.setup.range_source[n]
                           for n in lasers})
        try:
            return plan_form(form, lu.centred_patch(cal), self.app.machine,
                             simulated=self.app.simulated)
        except FormError as exc:
            self.app.status(f"line-up: {exc}", error=True)
            return None

    def start(self) -> None:
        if self.app.machine.geometry.reference_laser not in self.chosen():
            self.app.status(
                f"line-up: include laser "
                f"{self.app.machine.geometry.reference_laser}, the reference",
                error=True)
            return
        plan = self.plan()
        if plan is None:
            return
        if not plan.request.locate:
            self.app.status("line-up: needs a measured [photodiode] to place "
                            "the lasers from", error=True)
            return
        out = _out_folder(self.app)
        text = "\n".join((*plan.lines, *plan.warnings, "",
                          "The stage will home first and the lasers will "
                          "come on. " + INFRARED_NOTE,
                          f"Files go to {out}."))
        if not messagebox.askokcancel("Start the line-up?", text,
                                      parent=self.frame):
            return
        from multilbic.bench.report import provenance

        if not self.app.worker.start_lineup(plan.request, out, provenance()):
            self.app.refused("line-up")
            return
        self.table.delete(*self.table.get_children())
        _show(self.summary, ["mapping..."])

    def save(self) -> None:
        if not self.app.worker.save_lineup():
            self.app.refused("save")

    def show(self, lineup: lu.LineUp) -> None:
        self.table.delete(*self.table.get_children())
        for n in sorted(lineup.edges):
            e = lineup.edges[n]

            def edge(x: lu.Edge | None) -> str:
                if x is None:
                    return "-"
                return f"{x.position_mm:.3f}" + ("" if x.trusted else " ?")

            offset = lineup.proposal.get(n)
            self.table.insert("", "end", values=(
                n, edge(e.u), edge(e.v),
                "-" if e.shift_um is None else f"{e.shift_um:+.0f} µm",
                "-" if offset is None else
                f"{offset[0] * 1000:+.0f}, {offset[1] * 1000:+.0f}"))

    def handle(self, event: Event) -> None:
        if isinstance(event, LineUpEnded):
            lines: list[str] = []
            if event.lineup is not None:
                self.show(event.lineup)
                su, sv = event.lineup.spread_um()
                lines.append("The lasers put the cell's edges this far apart: "
                             + ", ".join(
                                 f"{axis} {s:.0f} µm" if s is not None
                                 else f"{axis} -"
                                 for axis, s in (("u", su), ("v", sv))))
                lines += [line for line in event.lineup.lines(self.app.machine)
                          if "cell_offset" in line or "left as" in line]
            if event.folder is not None:
                lines.append(f"run: {event.folder}")
            self.can_save = (event.lineup is not None
                             and bool(event.lineup.proposal)
                             and not event.error)
            if event.error:
                lines.append(f"nothing to save: {event.error}")
            _show(self.summary, lines)
        elif isinstance(event, MachineChanged) and self.can_save:
            self.can_save = False
            self.summary.configure(state="normal")
            self.summary.insert("end", f"\nsaved: {event.path}")
            self.summary.configure(state="disabled")
        elif isinstance(event, CalibrationChanged):
            # The panel takes the event first; show what it holds now.
            self.frame.after_idle(self._show_calibration)
        if isinstance(event, (StateChanged, LineUpEnded, MachineChanged)):
            self.refresh()

    def refresh(self) -> None:
        idle = self.app.state is State.IDLE
        _enable(self.start_btn, idle)
        _enable(self.save_btn, idle and self.can_save)


def _enable(widget: ttk.Widget, on: bool) -> None:
    widget.state(["!disabled"] if on else ["disabled"])
