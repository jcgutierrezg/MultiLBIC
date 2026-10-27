"""
Corner calibration at the machine.

`Calibrator` does the work - home, jog, light a laser, read the
photocurrent, record the corner, trace the outline, save - and returns
what it found; it parses nothing and prints nothing but progress.
`CalibrationPrompt` is the text interface on top of it that
`multilbic calibrate` gives you; the GUI drives the same `Calibrator`.

On start the stage homes, XY goes to the reference laser's position, AB
to its centre, and the reference laser comes on. You jog **XY** until
the laser spot sits on the sample's corner - the corner the sample
extends from towards +A and +B, which on this machine is its top-right
corner as you look at it (+A moves the sample up, +B right;
docs/hardware.md) - then fine-tune with AB if you like,
record it with `here`, give the size, and watch the laser trace the
outline with `trace`. If the outline sits on the sample, `save`.

Every jog ends moving up on its axis (`multilbic.run.motion`), so the
recorded position is on the same side of the backlash as every move a
run makes later.

Commands (case doesn't matter):

    keys                         jog with single keys (below)
    x+0.5  y-1  a+0.01  b-0.02   jog an axis by that many mm
    x+  a-                       jog by the current step
    step 0.05                    set the step
    move x=70 y=65 a=17.5        go to a position (any axes)
    centre                       AB back to its centre
    where                        print the position
    laser 2 | off                light a laser, or none
    read                         photocurrent now (finds edges in the dark)
    here                         record the corner
    size 10 10                   the sample's width (A) and height (B), mm
    trace                        light the reference laser along the outline
    ranges 1,2,3 [bias]          each laser's current range on this sample
    save [file]                  write the calibration
    help | quit

In key mode (`keys`), no Enter needed:

    d / a     X up / down   (A in AB mode)
    w / s     Y up / down   (B in AB mode)
    q         switch between XY and AB
    e         step 0.1 -> 1 -> 10 mm -> 0.1 ...
    Esc, Enter or Ctrl+C   back to typed commands

For finer than 0.1 mm, type a jog (`a+0.01`).

`check` mode puts a saved calibration's corner back under the beam, to
see that homing again put things back where they were.
"""

from __future__ import annotations

import contextlib
import json
import re
import threading
from collections.abc import Callable
from pathlib import Path

from multilbic.clock import SYSTEM_CLOCK, Clock
from multilbic.config.machine import MachineConfig
from multilbic.run.keys import CTRL_C, ESCAPE, KeySource, terminal_keys
from multilbic.run.motion import RunStopped, approach, check
from multilbic.run.ranges import (
    CHECK_FEED_MM_S,
    RangeCheck,
    check_result,
    grid_lines,
    ranges_from_dict,
    ranges_to_dict,
)
from multilbic.run.rows import ScanDevices
from multilbic.scan.geometry import Calibration, place
from multilbic.scan.timing import FIRST_MOVE_DELAY_S, Trapezoid, axis_accel

JOG_RE = re.compile(r"^([xyab])([+-])(\d*\.?\d*)$")
MOVE_RE = re.compile(r"([xyab])=(-?\d+\.?\d*)")
MAX_JOG_MM = 20.0
#: What `e` cycles through in key mode.
KEY_STEPS_MM = (0.1, 1.0, 10.0)
#: Key -> (index of the axis in the pair, direction).
KEY_JOGS = {"d": (0, 1), "a": (0, -1), "w": (1, 1), "s": (1, -1)}
KEY_PAIRS = ("xy", "ab")
AXES = ("x", "y", "a", "b")
#: How fast `trace` runs the spot round the outline.
TRACE_FEED_MM_S = 2.0


class Calibrator:
    """The calibration actions, for any interface. One thread drives
    it; `halt()` may be called from any other.

    Moving actions return the position afterwards (`{"X": .., "Y": ..,
    "A": .., "B": ..}`). `halt()` stops the one in progress at once
    (Marlin quickstop) and makes it raise `RunStopped`; the laser stays
    as it was. The next action starts afresh."""

    def __init__(
        self,
        devices: ScanDevices,
        machine: MachineConfig,
        *,
        sample: str,
        say: Callable[[str], None] = lambda text: None,
        clock: Clock = SYSTEM_CLOCK,
    ):
        self.devices = devices
        self.machine = machine
        self.sample = sample
        self.say = say
        self.clock = clock
        #: The sample's checked ranges, by laser (D25).
        self.ranges: dict[int, RangeCheck] = {}
        self.reference = machine.geometry.reference_laser
        self.corner_xy: tuple[float, float] | None = None
        self.corner_ab: tuple[float, float] | None = None
        self.size: tuple[float, float] | None = None
        self.saved: Path | None = None
        self._halt = threading.Event()

    # ---- start and end ----

    def start(self, check: Calibration | None = None) -> dict[str, float]:
        """Home, then either the reference laser at the AB centre or,
        given a saved calibration, its corner under the beam."""
        self._halt.clear()
        d = self.devices
        self.say("homing")
        d.marlin.home()
        d.smu.prepare(bias_v=0.0)
        d.smu.output_on()
        if check is None:
            x, y = self.machine.laser(self.reference).xy_centre_mm
            a, b = self.machine.ab.centre_mm
            position = self._approach(x=x, y=y, a=a, b=b)
        else:
            self.adopt(check)
            position = self._to_corner()
        d.laser.select(self.reference)
        return position

    def shut_down(self) -> list[str]:
        """Laser and SMU output off, trying both. Returns what failed."""
        failures = []
        for name, step in (
            ("laser off", self.devices.laser.off),
            ("SMU output off", self.devices.smu.output_off),
        ):
            try:
                step()
            except Exception as exc:
                failures.append(f"{name}: {exc}")
        return failures

    def halt(self) -> None:
        """Stop the move in progress. Safe from any thread."""
        self._halt.set()
        try:
            self.devices.marlin.quickstop()
        except Exception as exc:
            self.say(f"stop: quickstop failed: {exc}")

    # ---- moving ----

    def position(self) -> dict[str, float]:
        return self.devices.marlin.position()

    def jog(self, axis: str, distance: float) -> dict[str, float]:
        """Move one axis by `distance` mm, ending moving up."""
        axis = axis.lower()
        if axis not in AXES:
            raise ValueError(f"no axis {axis!r}: x, y, a or b")
        if abs(distance) > MAX_JOG_MM:
            raise ValueError(f"jogs are limited to {MAX_JOG_MM:g} mm")
        self._halt.clear()
        target = self.position()[axis.upper()] + distance
        return self._approach(**{axis: target})

    def move(self, **targets: float) -> dict[str, float]:
        """Go to a position, any of x, y, a, b."""
        if not targets or set(targets) - set(AXES):
            raise ValueError("move needs some of x, y, a, b")
        self._halt.clear()
        return self._approach(**targets)

    def centre(self) -> dict[str, float]:
        """AB back to its centre."""
        a, b = self.machine.ab.centre_mm
        return self.move(a=a, b=b)

    def to_corner(self) -> dict[str, float]:
        """Put the recorded corner back under the reference laser."""
        self._halt.clear()
        return self._to_corner()

    # Only the public actions clear the halt; what they call inside
    # must not, or a halted trace would carry on to the corner.

    def _to_corner(self) -> dict[str, float]:
        if self.corner_xy is None or self.corner_ab is None:
            raise ValueError("no corner yet")
        (x, y), (a, b) = self.corner_xy, self.corner_ab
        return self._approach(x=x, y=y, a=a, b=b)

    def _approach(self, **targets: float) -> dict[str, float]:
        return approach(
            self.devices.marlin, self.machine, stop=self._halt, **targets
        )

    # ---- lasers and the photocurrent ----

    def laser(self, number: int) -> None:
        """Light one laser; 0 turns them all off."""
        if number == 0:
            self.devices.laser.off()
        else:
            self.devices.laser.select(number)

    def read(self) -> float:
        """The photocurrent now, in A. In the dark, an edge is where it
        halves."""
        _, amps = self.devices.smu.measure(1)
        return amps

    # ---- the corner and the outline ----

    def here(self) -> dict[str, float]:
        """Record the corner where the stage is now."""
        p = self.position()
        self.corner_xy = (p["X"], p["Y"])
        self.corner_ab = (p["A"], p["B"])
        return p

    def set_size(self, width_mm: float, height_mm: float) -> None:
        """The sample's width (along A) and height (along B)."""
        if width_mm <= 0 or height_mm <= 0:
            raise ValueError("a sample needs a positive width and height")
        self.size = (width_mm, height_mm)

    def adopt(self, calibration: Calibration,
              ranges: dict[int, RangeCheck] | None = None) -> None:
        """Take the corner and size of a saved calibration, and its
        checked ranges if it has them, without moving."""
        if ranges is not None:
            self.ranges = dict(ranges)
        self.sample = calibration.sample
        self.corner_xy = calibration.corner_xy_mm
        self.corner_ab = calibration.corner_ab_mm
        self.size = (calibration.width_mm, calibration.height_mm)

    def calibration(self) -> Calibration:
        if self.corner_xy is None or self.corner_ab is None:
            raise ValueError("no corner yet: 'here' first")
        if self.size is None:
            raise ValueError("no size yet: 'size <width> <height>'")
        g = self.machine.geometry
        return Calibration(
            self.sample, self.reference,
            self.machine.laser(self.reference).xy_centre_mm,
            self.corner_xy, self.corner_ab, self.size[0], self.size[1],
            g.x_along, g.y_along,
        )

    def outline_ab(self) -> tuple[tuple[float, float], list[tuple[float, float]]]:
        """Where a run puts XY for the reference laser, and the sample's
        outline in AB there: from the calibration corner round and back
        to it."""
        placement = place(
            self.calibration(),
            self.machine.laser(self.reference).xy_centre_mm,
            self.machine.ab.centre_mm,
            self.reference,
        )
        frame = placement.frame
        a0, b0 = frame.origin_ab_mm
        a1, b1 = a0 + frame.width_mm, b0 + frame.height_mm
        return placement.xy_mm, [(a0, b0), (a1, b0), (a1, b1), (a0, b1), (a0, b0)]

    def trace(self) -> dict[str, float]:
        """Place the sample as a run would for the reference laser, and
        run the spot round its outline, ending back on the corner."""
        (x, y), outline = self.outline_ab()
        self._halt.clear()
        d = self.devices
        a0, b0 = outline[0]
        self._approach(x=x, y=y, a=a0, b=b0)
        d.laser.select(self.reference)
        self.say("tracing the outline")
        for a, b in outline[1:]:
            check(self._halt)
            d.marlin.move_to(feed_mm_s=TRACE_FEED_MM_S, a=a, b=b)
        d.marlin.wait_idle()
        # Back onto the corner the way it was recorded.
        return self._to_corner()

    def check_ranges(
        self, lasers: list[int] | tuple[int, ...], bias_v: float = 0.0,
    ) -> dict[int, RangeCheck]:
        """The sample's current range under each laser (D25): XY places
        the sample as a run will for it, the laser comes on, and the
        stage runs a coarse grid over the sample (`ranges.grid_lines`)
        while single readings are taken on autorange. Ends with the
        reference laser back on the corner; `halt()` stops it where it
        is. Returns the new checks, which `ranges` keeps for `save`."""
        calibration = self.calibration()
        if not lasers:
            raise ValueError("no lasers to check")
        self._halt.clear()
        d = self.devices
        accel = axis_accel(self.machine.ab.max_accel_mm_s2)
        checked: dict[int, RangeCheck] = {}
        # Autorange and the run's bias: what the run will see, read
        # without the stream, so autoranging costs nothing.
        d.smu.prepare(bias_v=bias_v)
        d.smu.output_on()
        try:
            for n in sorted(lasers):
                placement = place(
                    calibration, self.machine.laser(n).xy_centre_mm,
                    self.machine.ab.centre_mm, n,
                )
                lines = grid_lines(placement.frame)
                x, y = placement.xy_mm
                (a, b), _ = lines[0]
                self._approach(x=x, y=y, a=a, b=b)
                d.laser.select(n)
                self.say(f"checking laser {n}'s range on the sample")
                readings: list[float] = []
                for (a0, b0), (a1, b1) in lines:
                    check(self._halt)
                    self._approach(a=a0, b=b0)
                    length = ((a1 - a0) ** 2 + (b1 - b0) ** 2) ** 0.5
                    d.marlin.move_to(feed_mm_s=CHECK_FEED_MM_S, a=a1, b=b1)
                    until = (self.clock.now() + FIRST_MOVE_DELAY_S
                             + Trapezoid(length, CHECK_FEED_MM_S,
                                         accel).duration_s)
                    while self.clock.now() < until:
                        check(self._halt)
                        readings.append(d.smu.measure(1)[1])
                    d.marlin.wait_idle()
                    check(self._halt)
                result = check_result(n, readings, bias_v)
                checked[n] = result
                self.ranges[n] = result
                self.say(
                    f"laser {n}: brightest {result.peak_a * 1e6:.3g} uA in "
                    f"{result.readings} readings: range "
                    f"{result.range_a * 1e6:g} uA"
                    + (" (at the check's limit: maybe brighter)"
                       if result.at_limit else "")
                )
        except RunStopped:
            self._restore_smu()
            raise
        self._restore_smu()
        d.laser.select(self.reference)
        self._to_corner()
        return checked

    def _restore_smu(self) -> None:
        """Back to calibration's own settings: 0 V, autorange."""
        try:
            self.devices.smu.prepare(bias_v=0.0)
            self.devices.smu.output_on()
        except Exception as exc:
            self.say(f"SMU back to 0 V failed: {exc}")

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        calibration = self.calibration()
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, object] = {"schema": "multilbic-calibration/1",
                                   **calibration.to_dict()}
        if self.ranges:
            data["current_ranges"] = ranges_to_dict(self.ranges)
        path.write_text(json.dumps(data, indent=2) + "\n")
        self.saved = path
        return path


class CalibrationPrompt:
    """The typed commands of `multilbic calibrate`, on a `Calibrator`."""

    def __init__(
        self,
        devices: ScanDevices,
        machine: MachineConfig,
        *,
        sample: str,
        read: Callable[[str], str] | None = None,
        write: Callable[[str], None] = print,
        default_path: str | Path = "calibration.json",
        keys: Callable[[], contextlib.AbstractContextManager[KeySource]]
        = terminal_keys,
        clock: Clock = SYSTEM_CLOCK,
    ):
        self.cal = Calibrator(devices, machine, sample=sample, say=write,
                              clock=clock)
        # Looked up when called, not bound here, so the terminal's
        # input() can be swapped in tests.
        self.read = read or (lambda prompt: input(prompt))
        self.write = write
        self.default_path = Path(default_path)
        self.step = 0.1
        self.keys = keys
        self.key_pair = "xy"
        self.key_step = KEY_STEPS_MM[0]

    # ---- start ----

    def start(self, check: Calibration | None = None) -> None:
        """Home, then either the reference laser at the AB centre or a
        saved calibration's corner under it."""
        position = self.cal.start(check)
        if check is None:
            self.write(
                f"laser {self.cal.reference} is on. Jog XY until the spot "
                "is on the sample's TOP-RIGHT corner as you look at it (the "
                "corner the sample extends from towards +A and +B), then "
                "'here'. 'help' lists commands."
            )
        else:
            self.write(
                "the saved corner is under the beam: is the spot on the "
                "corner? If not, jog and 'here' again."
            )
        self.where(position)

    def stop(self) -> None:
        for failure in self.cal.shut_down():
            self.write(f"shutdown: {failure}")

    # ---- the loop ----

    def loop(self) -> Path | None:
        """Read commands until `quit` or end of input. Returns the file
        saved last, if any."""
        while True:
            try:
                line = self.read("calibrate> ")
            except EOFError:
                break
            line = line.strip().lower()
            if not line:
                continue
            if line in ("quit", "exit", "q"):
                break
            try:
                self.command(line)
            except Exception as exc:
                self.write(f"error: {exc}")
        return self.cal.saved

    def command(self, line: str) -> None:
        cal = self.cal
        word, _, rest = line.partition(" ")
        jog = JOG_RE.match(line)
        if line == "keys":
            self.key_mode()
        elif jog:
            axis, sign, amount = jog.groups()
            distance = float(amount) if amount else self.step
            self.jog(axis, distance if sign == "+" else -distance)
        elif word == "step":
            self.step = float(rest)
            self.write(f"step {self.step:g} mm")
        elif word == "move":
            targets = {k: float(v) for k, v in MOVE_RE.findall(rest)}
            if not targets:
                raise ValueError("move needs e.g. x=70 a=17.5")
            self.where(cal.move(**targets))
        elif word in ("centre", "center"):
            self.where(cal.centre())
        elif word == "where":
            self.where()
        elif word == "laser":
            cal.laser(int(rest))
            self.write(f"laser {int(rest)} on")
        elif word == "off":
            cal.laser(0)
            self.write("lasers off")
        elif word == "read":
            self.write(f"{cal.read() * 1e9:.2f} nA")
        elif word == "here":
            self.here()
        elif word == "size":
            width, height = (float(v) for v in rest.split())
            cal.set_size(width, height)
            self.write(f"size {width:g} x {height:g} mm")
        elif word == "trace":
            self.trace()
        elif word == "ranges":
            self.ranges(rest)
        elif word == "save":
            path = cal.save(Path(rest) if rest else self.default_path)
            self.write(f"saved {path}")
        elif word == "help":
            assert __doc__ is not None
            self.write(__doc__.split("Commands", 1)[1].split("`check`")[0])
        else:
            raise ValueError(f"unknown command {line!r}; 'help' lists them")

    # ---- commands ----

    def jog(self, axis: str, distance: float) -> None:
        self.where(self.cal.jog(axis, distance))

    def key_mode(self) -> None:
        """Jog with single keys until Esc or Enter."""
        with self.keys() as keys:
            self.write(
                "key mode: wasd jog, q XY/AB, e step, Esc or Enter to leave"
            )
            self._key_status()
            while True:
                key = keys.read().lower()
                if key in (ESCAPE, "\r", "\n", CTRL_C):
                    break
                if key == "q":
                    self.key_pair = "ab" if self.key_pair == "xy" else "xy"
                    self._key_status()
                elif key == "e":
                    i = KEY_STEPS_MM.index(self.key_step)
                    self.key_step = KEY_STEPS_MM[(i + 1) % len(KEY_STEPS_MM)]
                    self._key_status()
                elif key in KEY_JOGS:
                    index, sign = KEY_JOGS[key]
                    axis = self.key_pair[index]
                    try:
                        self.jog(axis, sign * self.key_step)
                    except Exception as exc:
                        self.write(f"error: {exc}")
                    # Keys pressed during the move are dropped, so a
                    # held key doesn't queue moves.
                    keys.flush()
        self.write("typed commands again")

    def _key_status(self) -> None:
        self.write(
            f"[{self.key_pair.upper()}, {self.key_step:g} mm]"
        )

    def where(self, p: dict[str, float] | None = None) -> None:
        p = p or self.cal.position()
        self.write(
            f"X{p['X']:.3f} Y{p['Y']:.3f}  A{p['A']:.4f} B{p['B']:.4f}"
        )

    def here(self) -> None:
        p = self.cal.here()
        self.write(
            f"corner recorded at X{p['X']:.3f} Y{p['Y']:.3f} "
            f"A{p['A']:.4f} B{p['B']:.4f}"
        )
        if self.cal.size is None:
            self.write("now 'size <width> <height>' in mm")

    def ranges(self, rest: str) -> None:
        from multilbic.run.ranges import check_duration_s

        parts = rest.split()
        if not parts:
            raise ValueError("ranges needs lasers, e.g. 'ranges 1,2,3' "
                             "or 'ranges 1,2,3 0.5' for 0.5 V bias")
        lasers = [int(n) for n in parts[0].split(",")]
        bias = float(parts[1]) if len(parts) > 1 else 0.0
        frame_s = check_duration_s(self._frame(), len(lasers))
        self.write(f"checking lasers {lasers} at {bias:g} V: the stage "
                   f"runs a grid under each, about {frame_s:.0f} s")
        self.cal.check_ranges(lasers, bias)
        listing = ", ".join(f"{n}={r.range_a * 1e6:g}uA"
                            for n, r in sorted(self.cal.ranges.items()))
        self.write(f"ranges: {listing}; 'save' keeps them with the "
                   "calibration")

    def _frame(self):  # noqa: ANN202
        from multilbic.scan.geometry import place

        return place(self.cal.calibration(),
                     self.cal.machine.laser(self.cal.reference).xy_centre_mm,
                     self.cal.machine.ab.centre_mm,
                     self.cal.reference).frame

    def trace(self) -> None:
        self.cal.trace()
        self.write(
            "done: back on the corner. If the outline sat on the sample, "
            "'save'; if not, jog, 'here' and 'trace' again."
        )


def load_ranges(path: str | Path) -> dict[int, RangeCheck]:
    """A saved calibration's checked ranges; none in an older file."""
    data = json.loads(Path(path).read_text())
    return ranges_from_dict(data.get("current_ranges"))


def load_calibration(path: str | Path) -> Calibration:
    data = json.loads(Path(path).read_text())
    if data.get("schema") != "multilbic-calibration/1":
        raise ValueError(f"{path}: not a MultiLBIC calibration file")
    return Calibration.from_dict(data)
