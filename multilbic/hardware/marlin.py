"""
The Marlin client: G-code to the SKR 1.4 Turbo and replies back.

What the old script got wrong, and what this does instead
---------------------------------------------------------
`send_to_skr()` wrote a line and then looped on `readline()` until it saw
something that looked like an answer, on the Tk thread, forever if the
answer never came. It matched any line starting with "ok", or containing
"Count" or "A:", to whichever command happened to be waiting.

Here:

* **Every reply is matched to its command.** Commands go out with a line
  number and checksum (`N12 G1 A5*87`), the host protocol Marlin was
  built around. With `ADVANCED_OK` enabled, Marlin echoes the number in
  its `ok`, so a late `ok` from a command that already timed out is
  recognised as stale instead of being credited to the next one.
* **A reader thread owns the port.** It sorts every incoming line:
  `ok`, `busy:` keepalives, `Resend:` requests, errors, position reports.
  Callers block on their own command with a timeout and never read the
  port themselves.
* **`busy: processing` extends the wait.** `HOST_KEEPALIVE_FEATURE` sends
  it every 2 s during long commands, so `G28` or an `M400` at the end of
  a long row is limited by silence, not by total duration.
* **Stop jumps the queue.** `quickstop()` writes `M410` without waiting
  for the command in progress. Marlin's emergency parser acts on it as
  the bytes arrive. The line is also queued and answered with an `ok`
  later, and the matching logic expects that `ok`.
* **Limits are checked here, before Marlin sees the move.** Marlin
  silently clamps an over-speed feedrate (the old script's `F360` ran at
  2 mm/s) and an out-of-range target. This client refuses both, naming
  the axis.

Facts about Marlin 2.1.2.4 this relies on, checked in its source:

* plain `M114` reports the last *commanded* position, not where the
  stage is now (`report_current_position_projected`);
* `ok` with `ADVANCED_OK` is `ok N<line> P<planner free> B<buffer free>`;
* a bad line number or checksum produces `Error:...`, `Resend: <n>`, then
  a bare `ok` that belongs to no command.
"""

from __future__ import annotations

import collections
import re
import threading
from dataclasses import dataclass, field

from multilbic.clock import SYSTEM_CLOCK, Clock
from multilbic.config.machine import MachineConfig
from multilbic.hardware.link import LineLink, LinkClosed

DEFAULT_TIMEOUT_S = 5.0
HOME_TIMEOUT_S = 10.0  # of silence; busy keepalives arrive every 2 s
HISTORY_LINES = 64

POSITION_RE = re.compile(r"^X:-?\d")
_AXIS_VALUE_RE = re.compile(r"([XYZAB]):(-?\d+(?:\.\d+)?)")
_OK_N_RE = re.compile(r"\bN(\d+)")
_OK_P_RE = re.compile(r"\bP(\d+)")
_OK_B_RE = re.compile(r"\bB(\d+)")
_INFO_RE = re.compile(r"([A-Z_]+):(.*?)(?=\s[A-Z_]+:|$)")

MOTION_AXES = ("X", "Y", "A", "B")


class MarlinError(RuntimeError):
    """Something went wrong talking to Marlin."""


class MarlinTimeout(MarlinError):
    """No reply, and no keepalive, within the timeout."""


class MarlinHalted(MarlinError):
    """Marlin reported `kill()`: it ignores everything until reset."""


class MarlinCommandError(MarlinError):
    """Marlin answered the command with an error or 'Unknown command'."""


class MotionLimitError(ValueError):
    """A move this client refuses: outside the safe range or too fast."""


def checksum(text: str) -> int:
    """Marlin's line checksum: XOR of every byte before the '*'."""
    value = 0
    for byte in text.encode("ascii"):
        value ^= byte
    return value


def parse_position(line: str) -> dict[str, float]:
    """`X:1.0 Y:2.0 ... Count X:400 ...` -> {'X': 1.0, ...}.

    Only the part before "Count" is read: after it come step counts,
    which use the same letters.
    """
    logical = line.split("Count", 1)[0]
    return {axis: float(v) for axis, v in _AXIS_VALUE_RE.findall(logical)}


@dataclass(frozen=True)
class Reply:
    command: str
    lines: tuple[str, ...]
    ok: str
    planner_free: int | None
    buffer_free: int | None


@dataclass(frozen=True)
class MarlinInfo:
    firmware_name: str
    machine_type: str
    fields: dict[str, str]
    capabilities: dict[str, str]


@dataclass
class _Pending:
    number: int | None
    wire: str
    command: str
    last_activity: float
    lines: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    ok: str | None = None
    failure: Exception | None = None
    done: threading.Event = field(default_factory=threading.Event)


class Marlin:
    def __init__(
        self,
        link: LineLink,
        machine: MachineConfig,
        clock: Clock = SYSTEM_CLOCK,
    ):
        self._link = link
        self._machine = machine
        self._clock = clock
        self._lock = threading.Lock()  # pending list and reader state
        self._write_lock = threading.Lock()  # numbering + write order
        self._command_lock = threading.Lock()  # one ordinary command
        self._pending: list[_Pending] = []
        self._history: dict[int, str] = {}
        self._next_number = 1
        self._swallow_ok = 0
        self._reader: threading.Thread | None = None
        self._running = False
        self.halted = False
        self.homed = False
        #: False after motors are released: the stage may have been
        #: pushed by hand, and Marlin's coordinates no longer mean
        #: anything until the next home.
        self.position_trusted = False
        self._commanded: dict[str, float] | None = None
        self.last_report: dict[str, float] | None = None
        #: (clock time, ">" or "<", line), for the GUI console.
        self.traffic: collections.deque[tuple[float, str, str]] = (
            collections.deque(maxlen=500)
        )
        self.info: MarlinInfo | None = None
        #: Cleared if Marlin ever answers a numbered line with a bare
        #: ok, meaning replies are matched by order rather than number.
        self.advanced_ok = True

    # ---- lifecycle ----

    def open(self) -> MarlinInfo:
        """Start the reader, reset line numbering, identify the board.

        Refuses a controller whose MACHINE_TYPE is not this machine's
        name: a wrong port must fail here, not at the first move.
        """
        self._running = True
        self._reader = threading.Thread(
            target=self._read_loop, name="marlin-reader", daemon=True
        )
        self._reader.start()
        self._send_unnumbered("M110 N0")
        with self._write_lock:
            self._next_number = 1
            self._history.clear()
        info = self._parse_info(self.send("M115").lines)
        if info.machine_type != self._machine.name:
            raise MarlinError(
                f"controller reports MACHINE_TYPE '{info.machine_type}', "
                f"expected '{self._machine.name}': wrong port?"
            )
        self.info = info
        self.send("G90")
        self.send("M154 S0")  # automatic position reports off
        self.position()
        return info

    def use_limits(self, machine: MachineConfig) -> None:
        """Check moves against `machine` from now on.

        For bench probes that change Marlin's limits at runtime (`M203`)
        and need this client to agree. Not for scans: those use the
        configured limits.
        """
        self._machine = machine

    def close(self) -> None:
        self._running = False
        self._link.close()
        if self._reader is not None:
            self._reader.join(timeout=2.0)

    # ---- commands ----

    def send(self, command: str, timeout: float = DEFAULT_TIMEOUT_S) -> Reply:
        """Send one command and wait for its `ok`.

        `timeout` is seconds of silence: each `busy:` keepalive restarts
        it.
        """
        with self._command_lock:
            entry = self._submit(command, numbered=True)
            return self._wait(entry, timeout)

    def _send_unnumbered(
        self, command: str, timeout: float = DEFAULT_TIMEOUT_S
    ) -> Reply:
        with self._command_lock:
            entry = self._submit(command, numbered=False)
            return self._wait(entry, timeout)

    def quickstop(self) -> None:
        """Stop all motion now (`M410`), without waiting for anything.

        Safe to call from any thread, including while another command
        is waiting: the emergency parser acts on the bytes as they
        arrive. The commanded position becomes unknown, because Marlin
        resets it to wherever the steppers actually stopped.
        """
        self._submit("M410", numbered=False)
        with self._lock:
            self._commanded = None

    def home(self) -> None:
        self.send("G28", timeout=HOME_TIMEOUT_S)
        self.homed = True
        self.position_trusted = True
        self.position()

    def wait_idle(self, timeout: float = DEFAULT_TIMEOUT_S) -> None:
        """Block until every queued move has finished (`M400`)."""
        self.send("M400", timeout=timeout)

    def position(self) -> dict[str, float]:
        """The last commanded position (`M114`), not a live reading.

        After `wait_idle()` the two are the same. During a move, Marlin
        reports the move's destination.
        """
        reply = self.send("M114")
        for line in reply.lines:
            if POSITION_RE.match(line):
                position = parse_position(line)
                with self._lock:
                    self._commanded = dict(position)
                return position
        raise MarlinError(f"M114 returned no position: {reply.lines}")

    def motors(self, on: bool) -> None:
        """Energise (`M17`) or release (`M18`) every stepper.

        Releasing lets the stage be pushed by hand, which Marlin cannot
        see, so positions are untrusted until the next `home()`.
        """
        self.send("M17" if on else "M18")
        if not on:
            self.position_trusted = False

    def settings(self) -> list[str]:
        """The settings Marlin is actually running (`M503`), which can
        differ from the compiled defaults because EEPROM is enabled."""
        return list(self.send("M503").lines)

    def move_to(
        self,
        *,
        feed_mm_s: float,
        x: float | None = None,
        y: float | None = None,
        a: float | None = None,
        b: float | None = None,
    ) -> Reply:
        """Queue an absolute straight move. Returns once Marlin has
        planned it, which is usually before it starts: follow with
        `wait_idle()` to wait for arrival.

        Refused unless the machine is homed and the motors have not been
        released since.
        """
        if not self.position_trusted:
            raise MarlinError(
                "position is not trusted (not homed, or motors were "
                "released): home first"
            )
        target = {"X": x, "Y": y, "A": a, "B": b}
        return self._move(
            {k: v for k, v in target.items() if v is not None},
            feed_mm_s,
            check_bounds=True,
        )

    def jog(
        self,
        *,
        feed_mm_s: float,
        dx: float = 0.0,
        dy: float = 0.0,
        da: float = 0.0,
        db: float = 0.0,
    ) -> Reply:
        """Move relative to the current position, for manual alignment.

        Allowed before homing, because that is when you need it. The
        range checks then apply only once homed, since unhomed
        coordinates say nothing about where the stage really is.
        """
        start = self._known_position()
        deltas = {"X": dx, "Y": dy, "A": da, "B": db}
        target = {
            axis: start[axis] + delta
            for axis, delta in deltas.items()
            if delta != 0.0
        }
        return self._move(target, feed_mm_s, check_bounds=self.homed)

    def _known_position(self) -> dict[str, float]:
        with self._lock:
            commanded = self._commanded
        return dict(commanded) if commanded is not None else self.position()

    def _move(
        self,
        target: dict[str, float],
        feed_mm_s: float,
        check_bounds: bool,
    ) -> Reply:
        if not target:
            raise MotionLimitError("move with no axis")
        start = self._known_position()
        if check_bounds:
            self._check_bounds(target)
        self._check_feed(start, target, feed_mm_s)
        words = " ".join(f"{axis}{value:.4f}" for axis, value in target.items())
        reply = self.send(f"G1 {words} F{feed_mm_s * 60:.3f}")
        with self._lock:
            if self._commanded is not None:
                self._commanded.update(target)
        return reply

    def _check_bounds(self, target: dict[str, float]) -> None:
        ab, xy = self._machine.ab, self._machine.xy
        limits = {
            "X": (0.0, xy.travel_mm[0]),
            "Y": (0.0, xy.travel_mm[1]),
            "A": (ab.safe_min_mm, ab.safe_max_mm),
            "B": (ab.safe_min_mm, ab.safe_max_mm),
        }
        for axis, value in target.items():
            low, high = limits[axis]
            if not low <= value <= high:
                raise MotionLimitError(
                    f"{axis}{value:.4f} is outside {low}..{high} mm"
                )

    def _check_feed(
        self,
        start: dict[str, float],
        target: dict[str, float],
        feed_mm_s: float,
    ) -> None:
        """Refuse a feedrate Marlin would silently clamp.

        Marlin scales a whole move down until no axis exceeds its own
        limit. The per-axis share of the feed is what each axis sees.
        """
        if feed_mm_s <= 0:
            raise MotionLimitError(f"feedrate {feed_mm_s} mm/s must be > 0")
        deltas = {axis: target[axis] - start.get(axis, 0.0) for axis in target}
        distance = sum(d * d for d in deltas.values()) ** 0.5
        if distance == 0:
            return
        max_feed = {
            "X": self._machine.xy.max_feed_mm_s,
            "Y": self._machine.xy.max_feed_mm_s,
            "A": self._machine.ab.max_feed_mm_s,
            "B": self._machine.ab.max_feed_mm_s,
        }
        for axis, delta in deltas.items():
            axis_speed = feed_mm_s * abs(delta) / distance
            if axis_speed > max_feed[axis] * (1 + 1e-9):
                raise MotionLimitError(
                    f"{axis} would move at {axis_speed:.3f} mm/s, above "
                    f"its {max_feed[axis]} mm/s limit: Marlin would "
                    f"silently slow the whole move"
                )

    # ---- wire ----

    def _submit(self, command: str, numbered: bool) -> _Pending:
        if self.halted:
            raise MarlinHalted("Marlin is halted; reset the controller")
        with self._write_lock:
            number: int | None = None
            wire = command
            if numbered:
                n = self._next_number
                self._next_number += 1
                body = f"N{n} {command}"
                wire = f"{body}*{checksum(body)}"
                self._history[n] = wire
                self._history.pop(n - HISTORY_LINES, None)
                number = n
            entry = _Pending(number, wire, command, self._clock.now())
            with self._lock:
                self._pending.append(entry)
            self._log(">", wire)
            try:
                self._link.write_line(wire)
            except LinkClosed as exc:
                with self._lock:
                    if entry in self._pending:
                        self._pending.remove(entry)
                raise MarlinError(f"link closed: {exc}") from exc
        return entry

    def _wait(self, entry: _Pending, timeout: float) -> Reply:
        while True:
            if entry.done.wait(self._clock.to_real(0.05)):
                break
            with self._lock:
                silent = self._clock.now() - entry.last_activity
                if silent > timeout and not entry.done.is_set():
                    if entry in self._pending:
                        self._pending.remove(entry)
                    raise MarlinTimeout(
                        f"no reply to '{entry.command}' for {timeout} s"
                    )
        if entry.failure is not None:
            raise entry.failure
        if entry.errors:
            raise MarlinCommandError(
                f"'{entry.command}': {'; '.join(entry.errors)}"
            )
        assert entry.ok is not None
        return Reply(
            entry.command,
            tuple(entry.lines),
            entry.ok,
            _int_or_none(_OK_P_RE, entry.ok),
            _int_or_none(_OK_B_RE, entry.ok),
        )

    def _read_loop(self) -> None:
        while self._running:
            try:
                line = self._link.read_line(0.2)
            except LinkClosed:
                self._fail_all(MarlinError("link closed"))
                return
            if line is None:
                continue
            self._log("<", line)
            self._handle(line.strip())

    def _handle(self, line: str) -> None:
        if not line:
            return
        with self._lock:
            oldest = self._pending[0] if self._pending else None
            if line.startswith("ok"):
                self._handle_ok(line)
            elif line.startswith(("echo:busy", "busy:")):
                for entry in self._pending:
                    entry.last_activity = self._clock.now()
            elif line.startswith("Resend:"):
                self._handle_resend(line)
            elif line.startswith("Error:"):
                if "kill()" in line or "halted" in line.lower():
                    self.halted = True
                    self._fail_all_locked(MarlinHalted(line))
                elif "Last Line" in line:
                    pass  # a Resend follows; that is what we act on
                elif oldest is not None:
                    oldest.errors.append(line)
            elif line.startswith("echo:Unknown command"):
                if oldest is not None:
                    oldest.errors.append(line[len("echo:") :])
            elif line == "start":
                self.homed = False
                self.position_trusted = False
                self._commanded = None
                self._fail_all_locked(
                    MarlinError("controller restarted ('start')")
                )
            elif POSITION_RE.match(line):
                if oldest is not None and oldest.command.startswith("M114"):
                    oldest.lines.append(line)
                else:
                    self.last_report = parse_position(line)
            elif oldest is not None:
                oldest.lines.append(line)

    def _handle_ok(self, line: str) -> None:
        if self._swallow_ok:
            # The bare ok Marlin sends after a Resend request.
            self._swallow_ok -= 1
            return
        number = _int_or_none(_OK_N_RE, line)
        match = next((e for e in self._pending if e.number == number), None)
        if match is None and number is None and self._pending:
            # Firmware without ADVANCED_OK sends a bare ok for numbered
            # lines too. Fall back to order, which is all such firmware
            # allows. `advanced_ok` records that this happened.
            match = self._pending[0]
            self.advanced_ok = False
        if match is None:
            # A late ok for a command that already timed out: ignored,
            # which is the point of numbering lines.
            self._log("!", f"unmatched ok ignored: {line}")
            return
        self._pending.remove(match)
        match.ok = line
        match.done.set()

    def _handle_resend(self, line: str) -> None:
        try:
            number = int(line.split(":", 1)[1])
        except ValueError:
            return
        self._swallow_ok += 1
        # Marlin wants every line from `number` on, in order.
        for n in range(number, self._next_number):
            wire = self._history.get(n)
            if wire is None:
                continue
            self._log(">", wire)
            self._link.write_line(wire)
        for entry in self._pending:
            entry.last_activity = self._clock.now()

    def _fail_all(self, error: Exception) -> None:
        with self._lock:
            self._fail_all_locked(error)

    def _fail_all_locked(self, error: Exception) -> None:
        for entry in self._pending:
            entry.failure = error
            entry.done.set()
        self._pending.clear()

    def _log(self, direction: str, line: str) -> None:
        self.traffic.append((self._clock.now(), direction, line))

    @staticmethod
    def _parse_info(lines: tuple[str, ...]) -> MarlinInfo:
        fields: dict[str, str] = {}
        capabilities: dict[str, str] = {}
        for line in lines:
            if line.startswith("Cap:"):
                name, _, value = line[4:].partition(":")
                capabilities[name] = value
            elif line.startswith("FIRMWARE_NAME:"):
                for key, value in _INFO_RE.findall(line):
                    fields[key] = value.strip()
        if "FIRMWARE_NAME" not in fields:
            raise MarlinError(f"M115 did not identify the firmware: {lines}")
        return MarlinInfo(
            fields["FIRMWARE_NAME"],
            fields.get("MACHINE_TYPE", ""),
            fields,
            capabilities,
        )


def _int_or_none(pattern: re.Pattern[str], text: str) -> int | None:
    match = pattern.search(text)
    return int(match.group(1)) if match else None
