"""
The machine behind the window: one thread that owns the devices.

The window never touches a device (SMUniversal rule 8, *the UI is a
queue*). It calls `MachineWorker`'s methods, which return at once, and
reads what happened from `drain()`, a few times a second:

    window --- connect / home / jog / here / trace / start_run ... ---> queue
    window <--- StateChanged, Position, Reading, RowEvent, RunEnded ... --- events

**One action at a time.** An action is accepted only while the machine
is `IDLE`; anything sent while it is busy is refused (the method returns
False), as key mode drops keys pressed while the stage moves. The state
changes on the caller's thread the moment an action is accepted, so two
quick clicks can't both get in.

**Stop** acts at once, from the window's thread: a run stops as Ctrl+C
stops it on the command line (`Session.request_stop`), a calibration
move stops through `Calibrator.halt()` with the laser left as it was,
and Stop while idle turns the laser off.

**While idle**, once the stage has been homed, the photocurrent is read
every `poll_s` and sent as `Reading`: it is how an edge is found.

States::

    DISCONNECTED -> CONNECTING -> IDLE <-> MOVING      (calibration actions)
                                   IDLE <-> RUNNING    (a run)
                     MOVING, RUNNING -> STOPPING -> IDLE
"""

from __future__ import annotations

import enum
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from multilbic.config.machine import MachineConfig
from multilbic.run.calibrate import Calibrator, load_calibration
from multilbic.run.devices import Connection
from multilbic.run.motion import RunStopped
from multilbic.run.rows import RowDone
from multilbic.run.session import (
    LaserOutcome,
    LaserPlan,
    RunOutcome,
    RunRequest,
    Session,
)
from multilbic.scan.geometry import Calibration

if TYPE_CHECKING:
    from multilbic.scan.mapping import MapResult

#: How often the photocurrent is read while idle.
POLL_S = 0.5


class State(enum.StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    IDLE = "idle"
    MOVING = "moving"
    RUNNING = "running"
    STOPPING = "stopping"


# ---- events, worker -> window ----


@dataclass(frozen=True)
class StateChanged:
    state: State


@dataclass(frozen=True)
class Log:
    text: str
    error: bool = False


@dataclass(frozen=True)
class Connected:
    simulated: bool
    firmware: dict[str, str | None]


@dataclass(frozen=True)
class Position:
    xyab: dict[str, float]


@dataclass(frozen=True)
class Reading:
    current_a: float


@dataclass(frozen=True)
class LaserChanged:
    #: 0 is all off.
    laser: int


@dataclass(frozen=True)
class CalibrationChanged:
    sample: str
    corner_xy: tuple[float, float] | None
    corner_ab: tuple[float, float] | None
    size: tuple[float, float] | None
    saved: Path | None
    #: Where a run puts XY for the reference laser, and the outline in
    #: AB there (`Calibrator.outline_ab`), once corner and size are set.
    outline: tuple[tuple[float, float], list[tuple[float, float]]] | None


@dataclass(frozen=True)
class RunStarted:
    folder: Path
    plans: tuple[LaserPlan, ...]


@dataclass(frozen=True)
class RowEvent:
    row: RowDone


@dataclass(frozen=True)
class MapEvent:
    laser: LaserOutcome
    result: MapResult


@dataclass(frozen=True)
class RunEnded:
    outcome: RunOutcome


Event = (
    StateChanged | Log | Connected | Position | Reading | LaserChanged
    | CalibrationChanged | RunStarted | RowEvent | MapEvent | RunEnded
)


@dataclass(frozen=True)
class _Job:
    name: str
    work: Callable[[], None]


_SHUTDOWN = _Job("shutdown", lambda: None)


class MachineWorker:
    def __init__(
        self,
        machine: MachineConfig,
        connector: Callable[[], Connection],
        *,
        sample: str = "sample",
        poll_s: float = POLL_S,
    ):
        self.machine = machine
        self._connector = connector
        self._sample = sample
        self._poll_s = poll_s
        self._events: queue.Queue[Event] = queue.Queue()
        self._jobs: queue.Queue[_Job] = queue.Queue()
        self._lock = threading.Lock()
        self._state = State.DISCONNECTED
        # Owned by the worker thread; Stop reaches these two through
        # their thread-safe halt/request_stop only.
        self._conn: Connection | None = None
        self._cal: Calibrator | None = None
        self._session: Session | None = None
        self._homed = False
        self._thread = threading.Thread(
            target=self._loop, name="machine", daemon=False
        )
        self._thread.start()

    # ---- what the window reads ----

    @property
    def state(self) -> State:
        with self._lock:
            return self._state

    def drain(self) -> list[Event]:
        """Every event since the last call, oldest first."""
        out: list[Event] = []
        while True:
            try:
                out.append(self._events.get_nowait())
            except queue.Empty:
                return out

    # ---- the connection ----

    def connect(self) -> bool:
        return self._submit(
            "connect", self._connect, State.CONNECTING,
            allowed=(State.DISCONNECTED,),
        )

    def disconnect(self) -> bool:
        return self._submit("disconnect", self._disconnect, State.MOVING)

    def close(self, timeout: float = 30.0) -> None:
        """Stop whatever runs, make everything safe, close the devices
        and end the thread. For the window's way out."""
        self.stop()
        self._jobs.put(_SHUTDOWN)
        self._thread.join(timeout)

    # ---- calibration ----

    def home(self) -> bool:
        """Home, and turn the SMU output on (0 V) for readings."""
        return self._moving("home", self._home)

    def start_calibration(self, check: Calibration | None = None) -> bool:
        """Home, then the reference laser over the AB centre, or a saved
        calibration's corner under it (`Calibrator.start`)."""
        def work() -> None:
            cal = self._calibrator()
            position = cal.start(check)
            self._homed = True
            self._emit(LaserChanged(cal.reference))
            self._emit(Position(position))
            self._calibration_changed()
        return self._moving("start calibration", work)

    def jog(self, axis: str, distance_mm: float) -> bool:
        return self._move("jog", lambda: self._calibrator().jog(
            axis, distance_mm))

    def move(self, **targets: float) -> bool:
        return self._move("move", lambda: self._calibrator().move(**targets))

    def centre(self) -> bool:
        return self._move("centre", lambda: self._calibrator().centre())

    def to_corner(self) -> bool:
        return self._move("to corner",
                          lambda: self._calibrator().to_corner())

    def laser(self, number: int) -> bool:
        def work() -> None:
            self._calibrator().laser(number)
            self._emit(LaserChanged(number))
        return self._moving("laser", work)

    def here(self) -> bool:
        def work() -> None:
            self._emit(Position(self._calibrator().here()))
            self._calibration_changed()
        return self._moving("here", work)

    def set_sample(self, name: str) -> bool:
        def work() -> None:
            self._calibrator().sample = name
            self._sample = name
            self._calibration_changed()
        return self._moving("sample", work)

    def set_size(self, width_mm: float, height_mm: float) -> bool:
        def work() -> None:
            self._calibrator().set_size(width_mm, height_mm)
            self._calibration_changed()
        return self._moving("size", work)

    def trace(self) -> bool:
        def work() -> None:
            cal = self._calibrator()
            self._emit(LaserChanged(cal.reference))
            self._emit(Position(cal.trace()))
        return self._moving("trace", work)

    def save(self, path: str | Path) -> bool:
        def work() -> None:
            saved = self._calibrator().save(path)
            self._log(f"calibration saved: {saved}")
            self._calibration_changed()
        return self._moving("save", work)

    def load(self, path: str | Path) -> bool:
        """A saved calibration's corner and size, without moving."""
        def work() -> None:
            cal = self._calibrator()
            cal.adopt(load_calibration(path))
            cal.saved = Path(path)
            self._sample = cal.sample
            self._log(f"calibration loaded: {path}")
            self._calibration_changed()
        return self._moving("load", work)

    # ---- runs ----

    def start_run(
        self,
        request: RunRequest,
        out_root: str | Path,
        provenance: dict[str, Any],
    ) -> bool:
        """A whole run, as `multilbic run` makes it. Check it first with
        `plan_run`, and ask the operator (D20)."""
        return self._submit(
            "run", lambda: self._run(request, Path(out_root), provenance),
            State.RUNNING,
        )

    # ---- Stop ----

    def stop(self) -> None:
        """Stop now, from any thread."""
        with self._lock:
            state = self._state
            if state is State.RUNNING:
                # Before the session exists, STOPPING is enough: the run
                # checks it before it starts.
                if self._session is not None:
                    self._session.request_stop()
                self._set_state_locked(State.STOPPING)
            elif state is State.MOVING and self._cal is not None:
                self._cal.halt()
                self._set_state_locked(State.STOPPING)
        if state is State.IDLE:
            self.laser(0)

    # ---- submitting ----

    def _submit(
        self,
        name: str,
        work: Callable[[], None],
        busy: State,
        *,
        allowed: tuple[State, ...] = (State.IDLE,),
    ) -> bool:
        with self._lock:
            if self._state not in allowed:
                return False
            self._set_state_locked(busy)
            self._jobs.put(_Job(name, work))
        return True

    def _moving(self, name: str, work: Callable[[], None]) -> bool:
        return self._submit(name, work, State.MOVING)

    def _move(self, name: str, move: Callable[[], dict[str, float]]) -> bool:
        return self._moving(name, lambda: self._emit(Position(move())))

    def _set_state_locked(self, state: State) -> None:
        if state is not self._state:
            self._state = state
            self._events.put(StateChanged(state))

    def _set_state(self, state: State) -> None:
        with self._lock:
            self._set_state_locked(state)

    def _emit(self, event: Event) -> None:
        self._events.put(event)

    def _log(self, text: str, error: bool = False) -> None:
        self._emit(Log(text, error))

    # ---- the worker thread ----

    def _loop(self) -> None:
        while True:
            try:
                job = self._jobs.get(timeout=self._poll_s)
            except queue.Empty:
                self._poll()
                continue
            if job is _SHUTDOWN:
                self._shut_down()
                return
            try:
                job.work()
            except RunStopped:
                self._log(f"{job.name}: stopped")
                self._position()
            except Exception as exc:
                self._log(f"{job.name} failed: {type(exc).__name__}: {exc}",
                          error=True)
            finally:
                with self._lock:
                    self._session = None
                    connected = self._conn is not None
                    self._set_state_locked(
                        State.IDLE if connected else State.DISCONNECTED
                    )

    def _poll(self) -> None:
        if self.state is not State.IDLE or not self._homed:
            return
        assert self._conn is not None
        try:
            _, amps = self._conn.devices.smu.measure(1)
        except Exception as exc:
            # Once, not every half second.
            self._homed = False
            self._log(f"reading stopped: {type(exc).__name__}: {exc}",
                      error=True)
            return
        self._emit(Reading(amps))

    def _position(self) -> None:
        if self._conn is None:
            return
        try:
            self._emit(Position(self._conn.devices.marlin.position()))
        except Exception as exc:
            self._log(f"position unknown: {exc}", error=True)

    def _calibrator(self) -> Calibrator:
        if self._cal is None:
            raise RuntimeError("not connected")
        return self._cal

    def _calibration_changed(self) -> None:
        cal = self._calibrator()
        outline = None
        if cal.corner_xy is not None and cal.size is not None:
            try:
                outline = cal.outline_ab()
            except ValueError:
                outline = None
        self._emit(CalibrationChanged(
            cal.sample, cal.corner_xy, cal.corner_ab, cal.size, cal.saved,
            outline,
        ))

    # ---- jobs, on the worker thread ----

    def _connect(self) -> None:
        conn = self._connector()
        self._conn = conn
        cal = Calibrator(conn.devices, self.machine, sample=self._sample,
                         say=self._log)
        with self._lock:
            self._cal = cal
        self._homed = False
        self._emit(Connected(conn.simulated, conn.firmware()))
        self._log("connected" + (" (simulated)" if conn.simulated else ""))

    def _disconnect(self) -> None:
        self._release()
        self._log("disconnected")

    def _home(self) -> None:
        d = self._calibrator().devices
        self._log("homing")
        d.marlin.home()
        d.smu.prepare(bias_v=0.0)
        d.smu.output_on()
        self._homed = True
        self._position()

    def _run(
        self, request: RunRequest, out_root: Path,
        provenance: dict[str, Any],
    ) -> None:
        conn = self._conn
        if conn is None:
            raise RuntimeError("not connected")
        if (not conn.simulated
                and not self.machine.geometry.directions_measured):
            raise RuntimeError(
                "[geometry] x_along/y_along in machine.toml have not been "
                "checked on the machine (directions_measured = false)"
            )
        session = Session(
            conn.devices, self.machine, conn.clock, request, out_root,
            simulated=conn.simulated, provenance=provenance, say=self._log,
            on_row=lambda row: self._emit(RowEvent(row)),
            on_map=lambda laser, result: self._emit(MapEvent(laser, result)),
        )
        with self._lock:
            if self._state is State.STOPPING:
                raise RunStopped("stopped before it started")
            self._session = session
        self._emit(RunStarted(session.folder, tuple(session.plans)))
        # The run ends with the SMU output off: no readings until the
        # next home.
        self._homed = False
        try:
            outcome = session.run()
        finally:
            self._emit(LaserChanged(0))
        self._emit(RunEnded(outcome))
        self._position()

    def _release(self) -> None:
        """Laser and SMU off, devices closed. Every step is tried."""
        cal, conn = self._cal, self._conn
        with self._lock:
            self._cal = None
        self._conn = None
        self._homed = False
        if cal is not None:
            for failure in cal.shut_down():
                self._log(f"shutdown: {failure}", error=True)
        if conn is not None:
            conn.close()

    def _shut_down(self) -> None:
        self._release()
        self._set_state(State.DISCONNECTED)
