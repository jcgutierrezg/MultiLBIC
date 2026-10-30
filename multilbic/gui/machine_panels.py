"""
The machine column of the window: connection, stage, lasers.

Each panel builds its widgets, turns clicks into `MachineWorker` calls,
and redraws from the worker's events (`handle`) and the machine's state
(`refresh`). None of them touches a device or waits for one.
"""

from __future__ import annotations

import functools
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from multilbic.gui import look
from multilbic.gui.jogkeys import (
    DIRECTIONS,
    KEYS,
    PAIRS,
    STEPS_MM,
    arrow_label,
    jog_for,
)
from multilbic.gui.worker import (
    Connected,
    Event,
    LaserChanged,
    Position,
    Reading,
    RowEvent,
    State,
    StateChanged,
)
from multilbic.run.ranges import AT_LIMIT_SHARE
from multilbic.run.rows import AUTORANGE_CURRENT_LIMIT_A as IDLE_LIMIT_A
from multilbic.scan.mapping import BASELINE_ROW

if TYPE_CHECKING:
    from multilbic.gui.app import App

#: The widest live reading: "-1.234 mA (limit)".
READOUT_CHARS = 17

#: How the device rows are labelled, and their key in `Connected.firmware`.
DEVICES = (("marlin", "Motion (SKR)"), ("laser", "Laser board"),
           ("smu", "miniSMU"))


class ConnectionPanel:
    def __init__(self, app: App, parent: tk.Misc):
        self.app = app
        self.frame = look.section(parent, "Machine")
        self.lamps: dict[str, tk.Canvas] = {}
        self.ids: dict[str, ttk.Label] = {}
        for row, (key, name) in enumerate(DEVICES):
            lamp = look.lamp(self.frame, app.theme)
            lamp.grid(row=row, column=0, padx=(0, 8), pady=2)
            ttk.Label(self.frame, text=name).grid(row=row, column=1,
                                                  sticky="w")
            ident = ttk.Label(self.frame, text="not connected",
                              style="Hint.TLabel")
            ident.grid(row=row, column=2, sticky="w", padx=(10, 0))
            self.lamps[key], self.ids[key] = lamp, ident
        buttons = ttk.Frame(self.frame)
        buttons.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.connect_btn = ttk.Button(buttons, text="Connect",
                                      command=self.connect)
        self.connect_btn.pack(side="left")
        self.disconnect_btn = ttk.Button(buttons, text="Disconnect",
                                         command=self.disconnect)
        self.disconnect_btn.pack(side="left", padx=(6, 0))
        ttk.Label(
            self.frame, style="Small.Hint.TLabel", wraplength=360,
            justify="left",
            text="After a Pi reboot the laser board and the miniSMU may "
                 "need their USB replugged before they answer.",
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.frame.columnconfigure(2, weight=1)

    def connect(self) -> None:
        if not self.app.worker.connect():
            self.app.refused("connect")

    def disconnect(self) -> None:
        if not self.app.worker.disconnect():
            self.app.refused("disconnect")

    def handle(self, event: Event) -> None:
        if isinstance(event, Connected):
            for key, _ in DEVICES:
                ident = event.firmware.get(key)
                look.set_lamp(self.lamps[key], self.app.theme,
                              "good" if ident else "bad")
                self.ids[key].configure(text=ident or "no answer")
        elif isinstance(event, StateChanged) and \
                event.state is State.DISCONNECTED:
            for key, _ in DEVICES:
                look.set_lamp(self.lamps[key], self.app.theme, "off")
                self.ids[key].configure(text="not connected")

    def refresh(self) -> None:
        state = self.app.state
        _enable(self.connect_btn, state is State.DISCONNECTED)
        _enable(self.disconnect_btn, state is State.IDLE)


class StagePanel:
    """Home, jog, go to, and where the stage is.

    Jog keys (D19) work only while the pad has the keyboard - click it,
    or Tab to it - so a stray key elsewhere can't move the stage. The
    ring round the pad turns the accent colour while they do.
    """

    def __init__(self, app: App, parent: tk.Misc):
        self.app = app
        self.frame = look.section(parent, "Stage")
        self.pair = tk.StringVar(master=app.root, value="xy")
        self.step = tk.DoubleVar(master=app.root, value=0.1)

        top = ttk.Frame(self.frame)
        top.grid(row=0, column=0, sticky="w")
        self.home_btn = ttk.Button(top, text="Home", command=self.home)
        self.home_btn.pack(side="left")
        self.centre_btn = ttk.Button(top, text="Centre AB",
                                     command=self.centre)
        self.centre_btn.pack(side="left", padx=(6, 0))
        self.motors_btn = ttk.Button(top, text="Motors off",
                                     command=self.motors_off)
        self.motors_btn.pack(side="left", padx=(6, 0))
        self.homed_label = ttk.Label(top, text="not homed",
                                     style="Warn.TLabel")
        self.homed_label.pack(side="left", padx=(12, 0))

        # Where the stage is.
        where = ttk.Frame(self.frame)
        where.grid(row=1, column=0, sticky="w", pady=(8, 4))
        self.position: dict[str, ttk.Label] = {}
        for column, axis in enumerate("XYAB"):
            ttk.Label(where, text=axis, style="Hint.TLabel").grid(
                row=0, column=column, sticky="w", padx=(0, 18))
            label = ttk.Label(where, text="-", style="Position.TLabel",
                              width=9)
            label.grid(row=1, column=column, sticky="w", padx=(0, 18))
            self.position[axis] = label

        # Axis pair and step.
        choose = ttk.Frame(self.frame)
        choose.grid(row=2, column=0, sticky="w", pady=(4, 4))
        self.choosers: list[ttk.Radiobutton] = []
        for pair in PAIRS:
            rb = ttk.Radiobutton(choose, text=pair.upper(), value=pair,
                                 variable=self.pair,
                                 command=self._relabel)
            rb.pack(side="left", padx=(0, 6))
            self.choosers.append(rb)
        ttk.Label(choose, text="step").pack(side="left", padx=(12, 6))
        for step in STEPS_MM:
            rb = ttk.Radiobutton(choose, text=f"{step:g}", value=step,
                                 variable=self.step)
            rb.pack(side="left", padx=(0, 4))
            self.choosers.append(rb)
        ttk.Label(choose, text="mm").pack(side="left")

        # The pad: arrows that move the spot the way they point.
        self.pad = ttk.Frame(self.frame, style="Keys.TFrame", padding=8,
                             takefocus=True)
        self.pad.grid(row=3, column=0, sticky="w", pady=(4, 2))
        self.arrows: dict[str, ttk.Button] = {}
        places = {"up": (0, 1), "left": (1, 0), "right": (1, 2),
                  "down": (2, 1)}
        for direction in DIRECTIONS:
            button = ttk.Button(self.pad, width=6, takefocus=False,
                                command=functools.partial(self.jog,
                                                          direction))
            r, c = places[direction]
            button.grid(row=r, column=c, padx=2, pady=2)
            self.arrows[direction] = button
        self.keys_label = ttk.Label(self.pad, style="Small.Hint.TLabel",
                                    anchor="center", width=12)
        self.keys_label.grid(row=1, column=1)
        ttk.Label(
            self.frame, style="Small.Hint.TLabel", wraplength=380,
            justify="left",
            text="Arrows move the spot on the sample as you see it. Click "
                 "the pad to use the keys: arrows or w a s d, q for XY/AB, "
                 "e for the step. Esc anywhere is Stop.",
        ).grid(row=4, column=0, sticky="w")
        self._bind_keys()
        self._relabel()

        # Go to a position.
        go = ttk.Frame(self.frame)
        go.grid(row=5, column=0, sticky="w", pady=(8, 0))
        self.targets: dict[str, ttk.Entry] = {}
        for axis in "XYAB":
            ttk.Label(go, text=axis).pack(side="left", padx=(0, 3))
            entry = ttk.Entry(go, width=8)
            entry.pack(side="left", padx=(0, 8))
            self.targets[axis] = entry
        self.go_btn = ttk.Button(go, text="Go", command=self.go)
        self.go_btn.pack(side="left")

    # ---- keys ----

    def _bind_keys(self) -> None:
        pad = self.pad
        for keysym in KEYS:
            pad.bind(f"<KeyPress-{keysym}>", self._on_key)
        for keysym in ("q", "Q", "e", "E"):
            pad.bind(f"<KeyPress-{keysym}>", self._on_key)
        pad.bind("<FocusIn>", lambda e: self._keys_shown(True))
        pad.bind("<FocusOut>", lambda e: self._keys_shown(False))
        # A click anywhere on the pad gives it the keys, buttons too.
        for widget in (pad, self.keys_label, *self.arrows.values()):
            widget.bind("<Button-1>", lambda e: pad.focus_set(), add="+")
        self._keys_shown(False)

    def _keys_shown(self, active: bool) -> None:
        self.pad.configure(style="KeysOn.TFrame" if active else "Keys.TFrame")
        self.keys_label.configure(
            text="keys on" if active else "click for keys",
            style="Accent.TLabel" if active else "Small.Hint.TLabel",
        )

    def _on_key(self, event: tk.Event) -> str:
        key = event.keysym
        if key in KEYS:
            # Held keys repeat; the worker refuses those that arrive
            # mid-move, so nothing queues up.
            self.jog(KEYS[key], quiet=True)
        elif key in ("q", "Q"):
            self.pair.set("ab" if self.pair.get() == "xy" else "xy")
            self._relabel()
        elif key in ("e", "E"):
            i = STEPS_MM.index(self.step.get()) if self.step.get() in \
                STEPS_MM else 0
            self.step.set(STEPS_MM[(i + 1) % len(STEPS_MM)])
        return "break"

    def _relabel(self) -> None:
        glyph = {"up": "▲", "down": "▼", "left": "◀",
                 "right": "▶"}
        for direction, button in self.arrows.items():
            label = arrow_label(direction, self.pair.get(), self.app.machine)
            button.configure(text=f"{glyph[direction]} {label}")

    # ---- actions ----

    def jog(self, direction: str, quiet: bool = False) -> None:
        if not self.app.homed or self.app.state in (State.RUNNING,
                                                    State.FOCUSING):
            return
        axis, sign = jog_for(direction, self.pair.get(), self.app.machine)
        if not self.app.worker.jog(axis, sign * self.step.get()) \
                and not quiet:
            self.app.refused("jog")

    def home(self) -> None:
        if not self.app.worker.home():
            self.app.refused("home")

    def centre(self) -> None:
        if not self.app.worker.centre():
            self.app.refused("centre")

    def motors_off(self) -> None:
        if not self.app.worker.motors_off():
            self.app.refused("motors off")

    def go(self) -> None:
        targets = {}
        for axis, entry in self.targets.items():
            text = entry.get().strip()
            if not text:
                continue
            try:
                targets[axis.lower()] = float(text)
            except ValueError:
                self.app.status(f"go to: {axis} {text!r} is not a number",
                                error=True)
                return
        if not targets:
            self.app.status("go to: type a position first", error=True)
            return
        if not self.app.worker.move(**targets):
            self.app.refused("go to")

    # ---- redrawing ----

    def handle(self, event: Event) -> None:
        if isinstance(event, Position):
            for axis, label in self.position.items():
                value = event.xyab.get(axis)
                digits = 3 if axis in "XY" else 4
                label.configure(
                    text="-" if value is None else f"{value:.{digits}f}")

    def refresh(self) -> None:
        app = self.app
        idle = app.state in (State.IDLE, State.MOVING)
        _enable(self.home_btn, idle)
        _enable(self.motors_btn, idle)
        movable = idle and app.homed
        for widget in (self.centre_btn, self.go_btn,
                       *self.arrows.values()):
            _enable(widget, movable)
        self.homed_label.configure(
            text="" if app.homed or not app.connected else "not homed")


class LaserPanel:
    """One button per laser, Off, and the photocurrent now."""

    def __init__(self, app: App, parent: tk.Misc):
        self.app = app
        self.frame = look.section(parent, "Lasers")
        self.buttons: dict[int, ttk.Button] = {}
        grid = ttk.Frame(self.frame)
        grid.grid(row=0, column=0, sticky="w")
        unmeasured = False
        colours = {n: app.laser_colour(n) for n in app.laser_numbers()}
        app.theme.on_change(lambda t: look.laser_styles(t, colours),
                            widget=self.frame)
        for i, laser in enumerate(app.machine.lasers):
            mark = "" if laser.measured else " *"
            unmeasured |= not laser.measured
            button = ttk.Button(
                grid, width=8,
                text=f"{laser.number}{mark}\n{laser.wavelength_nm} nm",
                image=look.swatch(grid, colours[laser.number]),
                compound="left",
                command=functools.partial(self.select, laser.number),
            )
            # Two rows of three: the revolver's two groups.
            button.grid(row=i // 3, column=i % 3, padx=2, pady=2)
            self.buttons[laser.number] = button
        self.off_btn = ttk.Button(grid, text="Off", width=6,
                                  command=lambda: self.select(0))
        self.off_btn.grid(row=0, column=3, rowspan=2, padx=(8, 0),
                          sticky="ns", pady=2)
        if unmeasured:
            ttk.Label(self.frame, style="Small.Hint.TLabel",
                      text="* position not measured yet: maps from it "
                           "land in the wrong place").grid(
                row=1, column=0, sticky="w", pady=(2, 0))
        # The readings one above the other, each as wide as the longest
        # it can be ("-1.234 mA (limit)"), so a reading that gains a
        # digit doesn't widen the column under everything else.
        reading = ttk.Frame(self.frame)
        reading.grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Label(reading, text="Cell").grid(row=0, column=0, sticky="w")
        self.current = ttk.Label(reading, text="-", style="Readout.TLabel",
                                 width=READOUT_CHARS, anchor="w")
        self.current.grid(row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Label(reading, text="Photodiode").grid(row=1, column=0,
                                                   sticky="w")
        self.photodiode = ttk.Label(reading, text="-",
                                    style="Readout.TLabel",
                                    width=READOUT_CHARS, anchor="w")
        self.photodiode.grid(row=1, column=1, sticky="w", padx=(12, 0))
        # Focus assist on the photodiode (Phase 6 step 6), in a window
        # of its own.
        self.focus_btn = ttk.Button(reading, text="Focus...", width=9,
                                    command=app.open_focus)
        if app.machine.photodiode is not None:
            self.focus_btn.grid(row=0, column=2, rowspan=2, padx=(12, 0))
        self.lit = 0

    def select(self, number: int) -> None:
        if not self.app.worker.laser(number):
            self.app.refused("laser")

    def handle(self, event: Event) -> None:
        if isinstance(event, LaserChanged):
            self.lit = event.laser
            for n, button in self.buttons.items():
                button.configure(style=f"Laser{n}.Lit.TButton"
                                 if n == event.laser else "TButton")
        elif isinstance(event, RowEvent):
            # A run switches lasers without asking the panel: its
            # blocks say which is on (none during the baseline).
            lit = 0 if event.row.row == BASELINE_ROW else event.row.laser
            if lit != self.lit:
                self.handle(LaserChanged(lit))
        elif isinstance(event, Reading):
            self.current.configure(text=reading_text(event.current_a))
            self.photodiode.configure(
                text=reading_text(event.photodiode_a))
        elif isinstance(event, StateChanged) and event.state in (
                State.RUNNING, State.FOCUSING, State.DISCONNECTED):
            self.current.configure(text="-")
            self.photodiode.configure(text="-")
            if event.state is State.DISCONNECTED:
                self.handle(LaserChanged(0))

    def refresh(self) -> None:
        usable = self.app.state in (State.IDLE, State.MOVING)
        for button in (*self.buttons.values(), self.off_btn):
            _enable(button, usable)
        _enable(self.focus_btn, self.app.connected)


def reading_text(amps: float | None) -> str:
    """A live reading, marked when it reaches the 1 mA limit the idle
    readings are taken with: the truth may be larger (laser 3 on the
    photodiode, bench 2026-10-29)."""
    if amps is not None and abs(amps) >= AT_LIMIT_SHARE * IDLE_LIMIT_A:
        return f"{look.amps(amps)} (limit)"
    return look.amps(amps)


def _enable(widget: ttk.Widget, on: bool) -> None:
    widget.state(["!disabled"] if on else ["disabled"])
