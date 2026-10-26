"""
Corner calibration at the machine: an interactive prompt.

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
from collections.abc import Callable
from pathlib import Path

from multilbic.config.machine import MachineConfig
from multilbic.run.keys import CTRL_C, ESCAPE, KeySource, terminal_keys
from multilbic.run.motion import approach
from multilbic.run.rows import ScanDevices
from multilbic.scan.geometry import Calibration, place

JOG_RE = re.compile(r"^([xyab])([+-])(\d*\.?\d*)$")
MOVE_RE = re.compile(r"([xyab])=(-?\d+\.?\d*)")
MAX_JOG_MM = 20.0
#: What `e` cycles through in key mode.
KEY_STEPS_MM = (0.1, 1.0, 10.0)
#: Key -> (index of the axis in the pair, direction).
KEY_JOGS = {"d": (0, 1), "a": (0, -1), "w": (1, 1), "s": (1, -1)}
KEY_PAIRS = ("xy", "ab")


class CalibrationPrompt:
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
    ):
        self.devices = devices
        self.machine = machine
        self.sample = sample
        # Looked up when called, not bound here, so the terminal's
        # input() can be swapped (tests, a GUI later).
        self.read = read or (lambda prompt: input(prompt))
        self.write = write
        self.default_path = Path(default_path)
        self.step = 0.1
        self.keys = keys
        self.key_pair = "xy"
        self.key_step = KEY_STEPS_MM[0]
        self.corner_xy: tuple[float, float] | None = None
        self.corner_ab: tuple[float, float] | None = None
        self.size: tuple[float, float] | None = None
        self.saved: Path | None = None
        self.reference = machine.geometry.reference_laser

    # ---- start ----

    def start(self, check: Calibration | None = None) -> None:
        """Home, then either the reference laser at the AB centre or a
        saved calibration's corner under it."""
        d = self.devices
        self.write("homing")
        d.marlin.home()
        d.smu.prepare(bias_v=0.0)
        d.smu.output_on()
        if check is None:
            x, y = self.machine.laser(self.reference).xy_centre_mm
            a, b = self.machine.ab.centre_mm
        else:
            x, y = check.corner_xy_mm
            a, b = check.corner_ab_mm
            self.corner_xy, self.corner_ab = check.corner_xy_mm, check.corner_ab_mm
            self.size = (check.width_mm, check.height_mm)
        approach(d.marlin, self.machine, x=x, y=y, a=a, b=b)
        d.laser.select(self.reference)
        if check is None:
            self.write(
                f"laser {self.reference} is on. Jog XY until the spot is on "
                "the sample's TOP-RIGHT corner as you look at it (the "
                "corner the sample extends from towards +A and +B), then "
                "'here'. 'help' lists commands."
            )
        else:
            self.write(
                "the saved corner is under the beam: is the spot on the "
                "corner? If not, jog and 'here' again."
            )
        self.where()

    def stop(self) -> None:
        for step in (self.devices.laser.off, self.devices.smu.output_off):
            try:
                step()
            except Exception as exc:
                self.write(f"shutdown: {exc}")

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
        return self.saved

    def command(self, line: str) -> None:
        word, _, rest = line.partition(" ")
        jog = JOG_RE.match(line)
        if line == "keys":
            self.key_mode()
        elif jog:
            axis, sign, amount = jog.groups()
            distance = float(amount) if amount else self.step
            if distance > MAX_JOG_MM:
                raise ValueError(f"jogs are limited to {MAX_JOG_MM:g} mm")
            self.jog(axis, distance if sign == "+" else -distance)
        elif word == "step":
            self.step = float(rest)
            self.write(f"step {self.step:g} mm")
        elif word == "move":
            targets = {k: float(v) for k, v in MOVE_RE.findall(rest)}
            if not targets:
                raise ValueError("move needs e.g. x=70 a=17.5")
            approach(self.devices.marlin, self.machine, **targets)
            self.where()
        elif word in ("centre", "center"):
            a, b = self.machine.ab.centre_mm
            approach(self.devices.marlin, self.machine, a=a, b=b)
            self.where()
        elif word == "where":
            self.where()
        elif word == "laser":
            self.devices.laser.select(int(rest))
            self.write(f"laser {int(rest)} on")
        elif word == "off":
            self.devices.laser.off()
            self.write("lasers off")
        elif word == "read":
            _, amps = self.devices.smu.measure(1)
            self.write(f"{amps * 1e9:.2f} nA")
        elif word == "here":
            self.here()
        elif word == "size":
            width, height = (float(v) for v in rest.split())
            self.size = (width, height)
            self.write(f"size {width:g} x {height:g} mm")
        elif word == "trace":
            self.trace()
        elif word == "save":
            self.save(Path(rest) if rest else self.default_path)
        elif word == "help":
            self.write(__doc__.split("Commands", 1)[1].split("`check`")[0])
        else:
            raise ValueError(f"unknown command {line!r}; 'help' lists them")

    # ---- commands ----

    def jog(self, axis: str, distance: float) -> None:
        position = self.devices.marlin.position()
        target = position[axis.upper()] + distance
        approach(self.devices.marlin, self.machine, **{axis: target})
        self.where()

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

    def where(self) -> None:
        p = self.devices.marlin.position()
        self.write(
            f"X{p['X']:.3f} Y{p['Y']:.3f}  A{p['A']:.4f} B{p['B']:.4f}"
        )

    def here(self) -> None:
        p = self.devices.marlin.position()
        self.corner_xy = (p["X"], p["Y"])
        self.corner_ab = (p["A"], p["B"])
        self.write(
            f"corner recorded at X{p['X']:.3f} Y{p['Y']:.3f} "
            f"A{p['A']:.4f} B{p['B']:.4f}"
        )
        if self.size is None:
            self.write("now 'size <width> <height>' in mm")

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

    def trace(self) -> None:
        """Place the sample as a run would for the reference laser, and
        run the spot round its outline, ending back on the corner."""
        calibration = self.calibration()
        placement = place(
            calibration,
            self.machine.laser(self.reference).xy_centre_mm,
            self.machine.ab.centre_mm,
            self.reference,
        )
        d = self.devices
        x, y = placement.xy_mm
        frame = placement.frame
        a0, b0 = frame.origin_ab_mm
        a1, b1 = a0 + frame.width_mm, b0 + frame.height_mm
        approach(d.marlin, self.machine, x=x, y=y, a=a0, b=b0)
        d.laser.select(self.reference)
        self.write("tracing the outline")
        for a, b in ((a1, b0), (a1, b1), (a0, b1), (a0, b0)):
            d.marlin.move_to(feed_mm_s=2.0, a=a, b=b)
        d.marlin.wait_idle()
        # Back onto the corner the way it was recorded.
        approach(
            d.marlin, self.machine,
            x=calibration.corner_xy_mm[0], y=calibration.corner_xy_mm[1],
            a=calibration.corner_ab_mm[0], b=calibration.corner_ab_mm[1],
        )
        self.write(
            "done: back on the corner. If the outline sat on the sample, "
            "'save'; if not, jog, 'here' and 'trace' again."
        )

    def save(self, path: Path) -> Path:
        calibration = self.calibration()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"schema": "multilbic-calibration/1", **calibration.to_dict()}
        path.write_text(json.dumps(data, indent=2) + "\n")
        self.saved = path
        self.write(f"saved {path}")
        return path


def load_calibration(path: str | Path) -> Calibration:
    data = json.loads(Path(path).read_text())
    if data.get("schema") != "multilbic-calibration/1":
        raise ValueError(f"{path}: not a MultiLBIC calibration file")
    return Calibration.from_dict(data)
