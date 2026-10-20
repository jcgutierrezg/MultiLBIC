"""
A simulated Marlin 2.1.2.4, configured like the MultiLBIC SKR.

It speaks the same text as the real board for the commands this project
sends, with the same quirks where they matter to a host: line numbers
and checksums are enforced, `ok` carries `N`/`P`/`B`, plain `M114`
reports the commanded position, `M410` acts through the emergency parser
and is answered again later, feedrates and targets are clamped silently,
the first move after an idle planner waits 100 ms, and long commands
send `busy: processing` every 2 s.

Faults can be injected for tests: a corrupted line (forces a resend), a
dropped `ok`, going silent, or a controller restart.

Backlash can be given per axis. The motors then follow Marlin's plan
exactly, but the stage they carry lags behind by up to half the
backlash, through a dead band: on a reversal the motor turns through
the whole backlash before the stage moves again. `stage_position()`
reports where the stage is, which is what a laser spot sees. Marlin's
own backlash compensation is effectively off on this machine (correction
0, `docs/hardware.md`), so nothing here undoes it.

Simulated time comes from the clock passed to `attach()`, so a
`ScaledClock` makes moves complete faster than real time while every
duration stays consistent.
"""

from __future__ import annotations

import bisect
import queue
import threading

from multilbic.clock import Clock
from multilbic.config.machine import MachineConfig
from multilbic.sim import motion
from multilbic.sim.motion import AXES, AxisLimits, Block

BUFSIZE = 4
BLOCK_BUFFER_SIZE = 16
FIRST_MOVE_DELAY_S = 0.100  # BLOCK_DELAY_FOR_1ST_MOVE in planner.cpp
#: After M410 the planner drops new moves for 1 s (cleaning_buffer_counter).
STOP_LOCKOUT_S = 1.0
KEEPALIVE_S = 2.0  # DEFAULT_KEEPALIVE_INTERVAL
DEFAULT_ACCEL_MM_S2 = 100.0
DEFAULT_FEED_MM_S = 25.0
EMERGENCY_COMMANDS = ("M410", "M112", "M108")
# Z has a driver and no motor; Marlin still needs its limits.
Z_LIMITS = AxisLimits(max_feed_mm_s=20.0, max_accel_mm_s2=100.0)
Z_TRAVEL_MM = 200.0
Z_STEPS_PER_MM = 400


def _strip_number(line: str) -> str:
    """'N12 G1 X1*34' -> 'G1 X1'."""
    text = line.strip()
    if "*" in text:
        text = text[: text.rindex("*")]
    if text.startswith("N"):
        parts = text.split(None, 1)
        text = parts[1] if len(parts) > 1 else ""
    return text.strip()


class FakeMarlin:
    def __init__(
        self,
        machine: MachineConfig,
        *,
        machine_type: str | None = None,
        home_duration_s: float = 2.0,
        reply_latency_s: float = 0.001,
        backlash_mm: dict[str, float] | None = None,
    ):
        self.machine = machine
        self.machine_type = machine_type or machine.name
        self.home_duration_s = home_duration_s
        self.reply_latency_s = reply_latency_s
        #: Lost motion per axis on a reversal, in mm.
        self.backlash_mm = {axis: 0.0 for axis in AXES}
        self.backlash_mm.update(backlash_mm or {})
        ab, xy = machine.ab, machine.xy
        self.limits = {
            "X": AxisLimits(xy.max_feed_mm_s, xy.max_accel_mm_s2),
            "Y": AxisLimits(xy.max_feed_mm_s, xy.max_accel_mm_s2),
            "Z": Z_LIMITS,
            "A": AxisLimits(ab.max_feed_mm_s, ab.max_accel_mm_s2),
            "B": AxisLimits(ab.max_feed_mm_s, ab.max_accel_mm_s2),
        }
        self.travel = {
            "X": xy.travel_mm[0],
            "Y": xy.travel_mm[1],
            "Z": Z_TRAVEL_MM,
            "A": ab.travel_mm,
            "B": ab.travel_mm,
        }
        self.steps_per_mm = {
            "X": xy.steps_per_mm,
            "Y": xy.steps_per_mm,
            "Z": Z_STEPS_PER_MM,
            "A": ab.steps_per_mm,
            "B": ab.steps_per_mm,
        }

        self._lock = threading.Lock()
        self._inbox: queue.Queue[str | None] = queue.Queue()
        self._emit = None
        self._clock: Clock | None = None
        self._worker: threading.Thread | None = None
        self._wake = threading.Event()

        # Marlin state
        #: Marlin's current_position: what M114 reports.
        self.commanded = {axis: 0.0 for axis in AXES}
        #: Marlin's planner.position: where the last accepted move ends.
        #: The two differ after a move dropped during the stop lockout.
        self.planned = {axis: 0.0 for axis in AXES}
        self.blocks: list[Block] = []
        #: Where the stage (not the motor) is when each block starts,
        #: by id(block), and where it is after the last planned move.
        self._load_start: dict[int, dict[str, float]] = {}
        self._load_planned = {axis: 0.0 for axis in AXES}
        #: Every block since the last home or stop, with the stage
        #: position it started from, kept after it ends: the ground
        #: truth a scan's mapped positions are checked against.
        self._trace: list[tuple[Block, dict[str, float]]] = []
        self._trace_starts: list[float] = []
        self._trace_rest = {axis: 0.0 for axis in AXES}
        self.relative = False
        self.feed_mm_s = DEFAULT_FEED_MM_S
        self.homed = False
        self.motors_on = False
        self.halted = False
        self.last_n = 0
        self.auto_report_s = 0.0
        self._lockout_until = float("-inf")
        #: Moves dropped during a post-stop lockout, for tests.
        self.dropped_moves = 0
        #: Every command executed, without line number or checksum.
        self.executed: list[str] = []

        # Fault injection
        self.corrupt_next_line = False
        self.drop_next_ok = False
        self.silent = False

    # ---- FakeDevice ----

    def attach(self, emit, clock: Clock) -> None:
        self._emit = emit
        self._clock = clock
        self._worker = threading.Thread(
            target=self._run, name="fake-marlin", daemon=True
        )
        self._worker.start()

    def receive(self, line: str) -> None:
        if self.halted or self.silent:
            return
        command = _strip_number(line).upper()
        word = command.split(None, 1)[0] if command else ""
        if word in EMERGENCY_COMMANDS:
            # The emergency parser acts as the bytes arrive...
            if word == "M410":
                self._quickstop()
            elif word == "M112":
                self._kill()
                return
        # ...and the line is still queued, and answered, like any other.
        self._inbox.put(line)

    def shutdown(self) -> None:
        self._inbox.put(None)

    # ---- simulation queries, for tests and the fake SMU ----

    def now(self) -> float:
        assert self._clock is not None
        return self._clock.now()

    def stage_position(self, t: float | None = None) -> dict[str, float]:
        """Where the stage physically is at time `t` (default: now),
        backlash included. Without backlash it is the motor position."""
        t = self.now() if t is None else t
        with self._lock:
            return self._load_at_locked(t)

    def past_stage_position(self, t: float) -> dict[str, float]:
        """Where the stage was at time `t`, even after the move has
        ended. Covers the time since the last home or quickstop."""
        with self._lock:
            i = bisect.bisect_right(self._trace_starts, t) - 1
            if i < 0:
                return dict(self._trace_rest)
            block, load = self._trace[i]
            if t >= block.t_end:
                return self._load_after(block, load, block.end)
            return self._load_after(block, load, block.position_at(t))

    def _reset_trace_locked(self, rest: dict[str, float]) -> None:
        self._trace.clear()
        self._trace_starts.clear()
        self._trace_rest = dict(rest)

    def motor_position(self, t: float | None = None) -> dict[str, float]:
        """Where Marlin has driven the motors at time `t`."""
        t = self.now() if t is None else t
        with self._lock:
            return self._position_at_locked(t)

    def moving(self) -> bool:
        with self._lock:
            return self._busy_locked()

    def inject_restart(self) -> None:
        """Behave as if the board reset: forget everything, say 'start'."""
        with self._lock:
            self.blocks.clear()
            self._load_start.clear()
            self.commanded = {axis: 0.0 for axis in AXES}
            self.planned = {axis: 0.0 for axis in AXES}
            self._load_planned = {axis: 0.0 for axis in AXES}
            self.homed = False
            self.last_n = 0
        self._send("start")

    # ---- internals ----

    def _send(self, line: str) -> None:
        if self._emit is not None and not self.halted:
            self._emit(line)

    def _run(self) -> None:
        while True:
            line = self._inbox.get()
            if line is None:
                return
            if self.halted or self.silent:
                continue
            if self.reply_latency_s:
                assert self._clock is not None
                self._clock.sleep(self.reply_latency_s)
            self._process(line)

    def _process(self, line: str) -> None:
        text = line.strip()
        number = None
        if text.startswith("N"):
            number = self._validate_numbered(text)
            if number is None:
                return
        command = _strip_number(text)
        if not command:
            return
        self.executed.append(command)
        word = command.split(None, 1)[0].upper()
        handler = getattr(self, f"_cmd_{word}", None)
        if handler is None:
            self._send(f'echo:Unknown command: "{command}"')
        else:
            handler(command)
        if self.halted:
            return
        if self.drop_next_ok:
            self.drop_next_ok = False
            return
        self._send(self._ok(number))

    def _validate_numbered(self, text: str) -> int | None:
        """Marlin's checks from `queue.cpp`. Returns the number, or None
        if the line was refused (after sending what Marlin sends)."""
        head = text.split(None, 1)[0]
        is_m110 = "M110" in text
        try:
            number = int(head[1:].split("*")[0])
            if is_m110:
                second = text.split("M110", 1)[1]
                if "N" in second:
                    number = int(second.split("N", 1)[1].split()[0].split("*")[0])
        except ValueError:
            self._line_error("Line Number is not Last Line Number+1")
            return None
        if number != self.last_n + 1 and not is_m110:
            if self.last_n - 1 <= number <= self.last_n:
                return None  # a duplicate after a resend: dropped silently
            self._line_error("Line Number is not Last Line Number+1")
            return None
        if "*" not in text:
            self._line_error("No Checksum with line number")
            return None
        body, _, given = text.rpartition("*")
        expected = 0
        for byte in body.encode("ascii"):
            expected ^= byte
        corrupted = self.corrupt_next_line
        self.corrupt_next_line = False
        if corrupted or given.strip() != str(expected):
            self._line_error("checksum mismatch")
            return None
        self.last_n = number
        return number

    def _line_error(self, message: str) -> None:
        self._send(f"Error:{message}, Last Line: {self.last_n}")
        self._send(f"Resend: {self.last_n + 1}")
        self._send("ok")

    def _ok(self, number: int | None) -> str:
        with self._lock:
            self._retire_locked(self.now())
            planner_free = BLOCK_BUFFER_SIZE - len(self.blocks)
        buffer_free = max(0, BUFSIZE - 1 - self._inbox.qsize())
        n = f" N{number}" if number is not None else ""
        return f"ok{n} P{planner_free} B{buffer_free}"

    # ---- motion ----

    def _retire_locked(self, t: float) -> None:
        while self.blocks and self.blocks[0].t_end <= t:
            self._load_start.pop(id(self.blocks.pop(0)), None)

    def _busy_locked(self) -> bool:
        self._retire_locked(self.now())
        return bool(self.blocks)

    def _planner_full_locked(self) -> bool:
        self._retire_locked(self.now())
        return len(self.blocks) >= BLOCK_BUFFER_SIZE

    def _position_at_locked(self, t: float) -> dict[str, float]:
        for block in self.blocks:
            if block.t_start <= t < block.t_end:
                return block.position_at(t)
            if t < block.t_start:
                return dict(block.start)
        if self.blocks and t >= self.blocks[-1].t_end:
            return dict(self.blocks[-1].end)
        return dict(self.planned)

    def _load_at_locked(self, t: float) -> dict[str, float]:
        for block in self.blocks:
            if t < block.t_end:
                start = self._load_start[id(block)]
                if t < block.t_start:
                    return dict(start)
                return self._load_after(block, start, block.position_at(t))
        return dict(self._load_planned)

    def _load_after(
        self,
        block: Block,
        load: dict[str, float],
        motor: dict[str, float],
    ) -> dict[str, float]:
        """The stage position once the motors of `block` reach `motor`,
        starting from `load`. Within one block each axis moves one way,
        so the stage follows the motor at half the backlash behind it,
        once the slack is taken up."""
        result = dict(load)
        for axis, m in motor.items():
            delta = block.end[axis] - block.start[axis]
            half = self.backlash_mm[axis] / 2
            if delta > 0:
                result[axis] = max(load[axis], m - half)
            elif delta < 0:
                result[axis] = min(load[axis], m + half)
        return result

    def _wait_while(self, condition, until=None) -> None:
        """Block like a synchronising Marlin command, with keepalives.

        `until()`, if given, says when the condition is next expected to
        change; the wait sleeps straight to it instead of polling."""
        next_keepalive = self.now() + KEEPALIVE_S
        while True:
            with self._lock:
                if not condition():
                    return
                wake = until() if until is not None else None
            if self.halted or self.silent:
                return
            now = self.now()
            if now >= next_keepalive:
                self._send("echo:busy: processing")
                next_keepalive += KEEPALIVE_S
            pause = 0.01
            if wake is not None and wake > now:
                pause = min(wake - now, next_keepalive - now)
            assert self._clock is not None
            self._clock.sleep(pause)

    def _queue_end_locked(self) -> float | None:
        return self.blocks[-1].t_end if self.blocks else None

    def _queue_move(self, target: dict[str, float]) -> None:
        self._wait_while(self._planner_full_locked)
        with self._lock:
            now = self.now()
            if self._locked_out_locked():
                # Marlin drops the move but still reports its target as
                # the position (current_position = destination).
                self.dropped_moves += 1
                self.commanded = dict(target)
                return
            self._retire_locked(now)
            if self.blocks:
                t_start = self.blocks[-1].t_end
            else:
                t_start = now + FIRST_MOVE_DELAY_S
            block = motion.plan(
                dict(self.planned),
                target,
                self.feed_mm_s,
                self.limits,
                DEFAULT_ACCEL_MM_S2,
                t_start,
            )
            if block.distance_mm > 0:
                self.blocks.append(block)
                self._load_start[id(block)] = self._load_planned
                self._trace.append((block, self._load_planned))
                self._trace_starts.append(block.t_start)
                self._load_planned = self._load_after(
                    block, self._load_planned, block.end
                )
            self.planned = dict(target)
            self.commanded = dict(target)
            self.motors_on = True  # Marlin enables steppers to move

    def _quickstop(self) -> None:
        with self._lock:
            # One instant for everything: the motors and the stage stop
            # together. Reading the clock twice let a stalled thread put
            # M114's position and the stage's apart (Ubuntu CI).
            now = self.now()
            position = self._position_at_locked(now)
            self._load_planned = self._load_at_locked(now)
            self._reset_trace_locked(self._load_planned)
            self.blocks.clear()
            self._load_start.clear()
            self.commanded = position
            self.planned = dict(position)
            self._lockout_until = now + STOP_LOCKOUT_S

    def _locked_out_locked(self) -> bool:
        return self.now() < self._lockout_until

    def _kill(self) -> None:
        with self._lock:
            self.blocks.clear()
            self._load_start.clear()
        self._send("Error:Printer halted. kill() called!")
        self.halted = True

    # ---- command handlers ----

    @staticmethod
    def _words(command: str) -> dict[str, float]:
        words = {}
        for token in command.split()[1:]:
            letter, value = token[0].upper(), token[1:]
            try:
                words[letter] = float(value)
            except ValueError:
                continue
        return words

    def _cmd_G0(self, command: str) -> None:
        self._cmd_G1(command)

    def _cmd_G1(self, command: str) -> None:
        words = self._words(command)
        if "F" in words and words["F"] > 0:
            self.feed_mm_s = words["F"] / 60.0
        target = dict(self.commanded)
        for axis in AXES:
            if axis in words:
                value = words[axis] + (target[axis] if self.relative else 0)
                # Software endstops: clamped, silently.
                target[axis] = min(max(value, 0.0), self.travel[axis])
        self._queue_move(target)

    def _cmd_G28(self, command: str) -> None:
        self._wait_while(self._busy_locked)
        words = command.upper().split()[1:]
        axes = [a for a in AXES if a in words] or list(AXES)
        assert self._clock is not None
        end = self.now() + self.home_duration_s
        self._wait_while(lambda: self.now() < end)
        with self._lock:
            for axis in axes:
                self.commanded[axis] = 0.0
                self.planned[axis] = 0.0
                self._load_planned[axis] = 0.0
            self._reset_trace_locked(self._load_planned)
            self.homed = True
            self.motors_on = True

    def _cmd_G90(self, command: str) -> None:
        self.relative = False

    def _cmd_G91(self, command: str) -> None:
        self.relative = True

    def _cmd_M400(self, command: str) -> None:
        # Marlin's synchronize() spins in idle(), so its ok follows the
        # last step within a fraction of a millisecond. Waking at the end
        # of the queue keeps the fake as prompt; polling alone would add
        # up to 10 ms, which the scan's row anchors would see.
        # planner.synchronize() also waits out the post-stop lockout.
        self._wait_while(
            lambda: self._busy_locked() or self._locked_out_locked(),
            until=self._queue_end_locked,
        )

    def _cmd_M410(self, command: str) -> None:
        self._quickstop()

    def _cmd_M110(self, command: str) -> None:
        words = self._words(command)
        if "N" in words:
            self.last_n = int(words["N"])

    def _cmd_M114(self, command: str) -> None:
        with self._lock:
            pos = dict(self.commanded)
        logical = " ".join(f"{axis}:{pos[axis]:.4f}" for axis in AXES)
        counts = " ".join(
            f"{axis}:{round(pos[axis] * self.steps_per_mm[axis])}"
            for axis in AXES
        )
        self._send(f"{logical} Count {counts}")

    def _cmd_M115(self, command: str) -> None:
        self._send(
            "FIRMWARE_NAME:Marlin 2.1.2.4 (Oct 17 2026 12:00:00) "
            "SOURCE_CODE_URL:github.com/MarlinFirmware/Marlin "
            f"PROTOCOL_VERSION:1.0 MACHINE_TYPE:{self.machine_type} "
            "EXTRUDER_COUNT:0 AXIS_COUNT:5 "
            "UUID:00000000-0000-0000-0000-000000000000"
        )
        for cap in ("EMERGENCY_PARSER:1", "AUTOREPORT_POS:1", "PROMPT_SUPPORT:1"):
            self._send(f"Cap:{cap}")

    def _cmd_M17(self, command: str) -> None:
        self.motors_on = True

    def _cmd_M18(self, command: str) -> None:
        self.motors_on = False

    def _cmd_M84(self, command: str) -> None:
        self.motors_on = False

    def _cmd_M154(self, command: str) -> None:
        self.auto_report_s = self._words(command).get("S", 0.0)

    def _cmd_M117(self, command: str) -> None:
        pass

    def _cmd_M203(self, command: str) -> None:
        words = self._words(command)
        for axis in AXES:
            if axis in words:
                old = self.limits[axis]
                self.limits[axis] = AxisLimits(words[axis], old.max_accel_mm_s2)

    def _cmd_M122(self, command: str) -> None:
        # A short stand-in for the TMC driver status table.
        self._send("\t\tX\tY\tZ\tA\tB")
        self._send("Enabled\t\t" + "\t".join(
            "true" if self.motors_on else "false" for _ in AXES
        ))
        self._send("Driver registers:")
        self._send("Testing X connection... OK")

    def _cmd_M503(self, command: str) -> None:
        def row(prefix: str, values: dict[str, float]) -> str:
            return "echo:  " + prefix + " " + " ".join(
                f"{axis}{values[axis]:.2f}" for axis in AXES
            )

        self._send("echo:; Steps per unit:")
        self._send(row("M92", {a: float(v) for a, v in self.steps_per_mm.items()}))
        self._send("echo:; Maximum feedrates (units/s):")
        self._send(row("M203", {a: lim.max_feed_mm_s for a, lim in self.limits.items()}))
        self._send("echo:; Maximum Acceleration (units/s2):")
        self._send(
            row("M201", {a: lim.max_accel_mm_s2 for a, lim in self.limits.items()})
        )
