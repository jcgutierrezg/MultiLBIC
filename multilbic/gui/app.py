"""
The MultiLBIC window.

    header:  name, version, SIMULATED, state ............ Theme Console STOP
    body:    machine (connection, stage, lasers) | sample | run
    footer:  the last thing that happened

Laid out for 1920x1080 (the Pi's monitor), opened maximised.

The window owns no device. Everything goes through a `MachineWorker`;
`_pump` reads its events every `PUMP_MS` on the Tk thread, which is the
only thread that touches a widget (SMUniversal rule 8).

**Stop** is the red button, or Esc anywhere in the window. **Closing**
during a run asks first, then stops the run and waits for it to make
everything safe before the window goes (D17).
"""

from __future__ import annotations

import datetime
import tkinter as tk
from importlib.metadata import version
from tkinter import messagebox, ttk
from typing import Protocol

from smuniversal_lab_suite.core.gui.console_panel import (
    ConsoleLog,
    ConsoleWindow,
    toggle_console,
)
from smuniversal_lab_suite.core.gui.theme import Theme, set_dark_title_bar

from multilbic.config.machine import MachineConfig
from multilbic.gui import look
from multilbic.gui.machine_panels import (
    ConnectionPanel,
    LaserPanel,
    StagePanel,
)
from multilbic.gui.run_panel import RunPanel
from multilbic.gui.sample_panels import CalibrationPanel, RunSetupPanel
from multilbic.gui.worker import (
    Event,
    Homed,
    Log,
    MachineWorker,
    State,
    StateChanged,
)
from multilbic.scan.geometry import Calibration

PUMP_MS = 50


class Panel(Protocol):
    """What the window asks of each panel."""

    def handle(self, event: Event) -> None: ...

    def refresh(self) -> None: ...

#: Width of the machine column; the other two share the rest.
MACHINE_COLUMN_PX = 470
STATE_TEXT = {
    State.DISCONNECTED: "not connected",
    State.CONNECTING: "connecting...",
    State.IDLE: "ready",
    State.MOVING: "busy",
    State.RUNNING: "running",
    State.STOPPING: "stopping...",
}


class App:
    def __init__(
        self,
        root: tk.Tk | tk.Toplevel,
        machine: MachineConfig,
        worker: MachineWorker,
        *,
        simulated: bool,
        theme: Theme | None = None,
    ):
        self.root = root
        self.machine = machine
        self.worker = worker
        self.simulated = simulated
        self.theme = theme or look.make_theme(root)
        self.state = worker.state
        self.connected = False
        self.homed = False
        # SMUniversal's console window reads these two.
        self.console_log = ConsoleLog()
        self.console_window: ConsoleWindow | None = None
        self._closing = False
        self._pump_id: str | None = None

        root.title("MultiLBIC" + (" (simulated)" if simulated else ""))
        root.minsize(1280, 720)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Destroy>", self._destroyed, add="+")
        # On the window, so it reaches every widget in it (a toplevel's
        # bindings are in each of its widgets' bindtags).
        root.bind("<Escape>", lambda e: self.stop())
        tk_root = root._root()  # type: ignore[union-attr]
        tk_root.report_callback_exception = self._callback_failed
        self.theme.on_change(self._repaint)

        self._build_header()
        self._repaint(self.theme)
        body = ttk.Frame(root, padding=(10, 8))
        body.grid(row=1, column=0, sticky="nsew")
        root.rowconfigure(1, weight=1)
        root.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, minsize=MACHINE_COLUMN_PX)
        body.columnconfigure(1, weight=2, uniform="rest")
        body.columnconfigure(2, weight=3, uniform="rest")

        column = ttk.Frame(body)
        column.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.connection = ConnectionPanel(self, column)
        self.stage = StagePanel(self, column)
        self.lasers = LaserPanel(self, column)
        for panel in (self.connection, self.stage, self.lasers):
            panel.frame.pack(fill="x", pady=(0, 8))

        middle = ttk.Frame(body)
        middle.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
        self.calibration_panel = CalibrationPanel(self, middle)
        self.setup = RunSetupPanel(self, middle)
        for frame in (self.calibration_panel.frame, self.setup.frame):
            frame.pack(fill="x", pady=(0, 8))

        self.run_panel = RunPanel(self, body)
        self.run_panel.frame.grid(row=0, column=2, sticky="nsew")
        self.panels: tuple[Panel, ...] = (
            self.connection, self.stage, self.lasers,
            self.calibration_panel, self.setup, self.run_panel)

        footer = ttk.Frame(root, padding=(10, 2, 10, 6))
        footer.grid(row=2, column=0, sticky="ew")
        self.status_label = ttk.Label(footer, text="", style="Hint.TLabel")
        self.status_label.pack(side="left")

        self._refresh()
        self._pump_id = root.after(PUMP_MS, self._pump)

    # ---- header ----

    def _build_header(self) -> None:
        header = ttk.Frame(self.root, style="Header.TFrame", padding=(12, 8))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="MultiLBIC", style="Title.Header.TLabel") \
            .pack(side="left")
        ttk.Label(header, text=version("multilbic"),
                  style="Sub.Header.TLabel").pack(side="left", padx=(8, 0))
        if self.simulated:
            ttk.Label(header, text="SIMULATED", style="Warn.Bold.TLabel") \
                .pack(side="left", padx=(16, 0))
        self.state_label = ttk.Label(header, text="",
                                     style="Header.TLabel")
        self.state_label.pack(side="left", padx=(24, 0))

        self.stop_btn = ttk.Button(header, text="STOP",
                                   style="Big.Stop.TButton",
                                   command=self.stop)
        self.stop_btn.pack(side="right")
        ttk.Button(header, text="Console", style="Header.TButton",
                   command=lambda: toggle_console(self)) \
            .pack(side="right", padx=(0, 16))
        self.mode_btn = ttk.Button(header, style="Header.TButton", width=6,
                                   command=self._toggle_mode)
        self.mode_btn.pack(side="right", padx=(0, 6))

    def _toggle_mode(self) -> None:
        self.theme.toggle()

    def _repaint(self, theme: Theme) -> None:
        self.root.configure(background=theme.palette.bg)
        set_dark_title_bar(self.root, theme.is_dark)
        if hasattr(self, "mode_btn"):
            self.mode_btn.configure(text="Light" if theme.is_dark else "Dark")

    # ---- what panels call ----

    def stop(self) -> None:
        if self.state in (State.DISCONNECTED, State.CONNECTING):
            return
        self.worker.stop()
        self.status("Stop pressed")

    def calibration(self) -> Calibration | None:
        """The calibration a run would start from now."""
        return self.calibration_panel.current()

    def calibration_changed(self) -> None:
        if hasattr(self, "setup"):
            self.setup.changed()

    def refused(self, what: str) -> None:
        if self.state is State.RUNNING:
            self.status(f"{what}: not during a run", error=True)
        elif self.state is State.DISCONNECTED:
            self.status(f"{what}: connect first", error=True)
        else:
            self.status(f"{what}: busy, wait for the last action to finish",
                        error=True)

    def status(self, text: str, error: bool = False) -> None:
        self.status_label.configure(
            text=text, style="Bad.TLabel" if error else "Hint.TLabel")
        self._console(text, error)

    # ---- events ----

    def _pump(self) -> None:
        self._pump_id = None
        for event in self.worker.drain():
            self.handle(event)
        if self._closing and self.worker.state in (
                State.IDLE, State.DISCONNECTED):
            self._finish_close()
            return
        self._pump_id = self.root.after(PUMP_MS, self._pump)

    def handle(self, event: Event) -> None:
        if isinstance(event, StateChanged):
            self.state = event.state
            if event.state is State.DISCONNECTED:
                self.connected = False
                self.homed = False
            elif event.state is State.IDLE:
                self.connected = True
        elif isinstance(event, Homed):
            self.homed = event.homed
        elif isinstance(event, Log):
            self.status(event.text, error=event.error)
        for panel in self.panels:
            panel.handle(event)
        if isinstance(event, (StateChanged, Homed)):
            self._refresh()

    def _refresh(self) -> None:
        self.state_label.configure(text=STATE_TEXT[self.state])
        self.stop_btn.state(
            ["disabled"] if self.state in (State.DISCONNECTED,
                                           State.CONNECTING)
            else ["!disabled"])
        for panel in self.panels:
            panel.refresh()

    def _console(self, text: str, error: bool) -> None:
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        mark = "! " if error else ""
        self.console_log.append(f"{stamp}  {mark}{text}\n")

    def _callback_failed(self, kind, value, tb) -> None:  # noqa: ANN001
        import traceback

        self._console("".join(traceback.format_exception(kind, value, tb)),
                      error=True)
        self.status(f"window error: {kind.__name__}: {value}", error=True)

    # ---- closing ----

    def close(self) -> None:
        """The window's close button: during a run, ask, then Stop and
        wait for the worker to make everything safe."""
        if self._closing:
            return
        if self.state in (State.RUNNING, State.STOPPING):
            if not messagebox.askyesno(
                "Stop the run?",
                "A run is in progress. Stop it and close? Finished rows "
                "stay on disk.",
                parent=self.root,
            ):
                return
        self._closing = True
        self.status("closing: making everything safe")
        self.worker.stop()

    def _destroyed(self, event: tk.Event) -> None:
        # <Destroy> reaches the window once for every widget in it.
        if event.widget is self.root and self._pump_id is not None:
            self.root.after_cancel(self._pump_id)
            self._pump_id = None

    def _finish_close(self) -> None:
        self.worker.close()
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def launch(machine: MachineConfig, *, simulated: bool, speedup: float) -> int:
    """Open the window, connect, and run until it is closed. Whatever
    ends the window, the worker is closed: a run is stopped and every
    device made safe."""
    from smuniversal_lab_suite.core.gui.maximize import maximize

    from multilbic.run.devices import open_real, open_sim

    def connector():
        if simulated:
            return open_sim(machine, speed=speedup)
        return open_real(machine)

    worker = MachineWorker(machine, connector)
    try:
        root = tk.Tk()
        App(root, machine, worker, simulated=simulated)
        maximize(root)
        # Opening the ports moves nothing, so connect straight away.
        worker.connect()
        root.mainloop()
    finally:
        worker.close()
    return 0
