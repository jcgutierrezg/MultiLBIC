"""
A laser module on the miniSMU: how it takes power, for the new laser board.

    python -m multilbic.bench.laser_module --real --polarity-check
    python -m multilbic.bench.laser_module --real --dummy-load --i-known 20m
    python -m multilbic.bench.laser_module --real --laser 4 --i-known 32m --v-known 3.1
    python -m multilbic.bench.laser_module --sim --module starved

The module is unplugged from the laser board and wired straight to
channel 1; the photodiode stays on channel 2 with the beam parked on it.
Nothing else is in the circuit.

Keeping the diode safe
----------------------
The modules' ratings are unknown, and today's operating point is no
guide for lasers 1 and 2, which the board starves. So the limits are
absolute, and the laser's own curve says when to stop:

* **Current is what's forced**, in `--i-step` steps (0.5 mA) that
  shrink as the light nears its ceiling: each at most half the room
  left at the slope just measured. A forced current can't run away the
  way a forced voltage can on a module with no regulator inside.
* **Light ceiling: 5 mW** (`--max-mw` may only lower it), read from the
  photodiode through its response to that laser, measured with the
  power meter (the Maintenance window's Power tab, `pd_response_a_w`).
  The sweep stops at 80 % of it as the photodiode reads, because a small
  spot can make the photodiode under-read; at 65 % with
  `--datasheet-response` (no power-meter calibration: the S1223-01's
  typical curve, refused otherwise).
* **The curve itself**: the sweep stops if the light per extra mA falls
  15 % below its best (thermal rollover beginning), if the light falls,
  or if it stops following the current (the beam off the photodiode
  would blind the light ceiling).
* **The beam must be seen**: light by 1.5 x `--i-known`, the current the
  module draws on the laser board today (multimeter in series), or the
  run stops. That is the only use of today's current: it is not a limit.
* **Voltage never above 5.5 V**; **current never above 120 mA**
  (`--max-ma` may lower it), whatever else happens. A module's own
  regulator shows as the voltage jumping to 5.5 V when the forced
  current passes what it allows; that ends the sweep too.
* **No reverse voltage**: every level is zero or positive, and channel 1
  goes to zero before it is switched off or changes mode. Reverse
  wiring is the one thing the probe can't see in time: `--polarity-check`
  puts +1.00 V (1 mA limit) on channel 1 with nothing connected, to
  find which terminal is + with the multimeter.
* **Dry run first** with `--dummy-load` (a 100 ohm resistor in the
  module's place): every stage, no light checks, and the report says
  whether the instrument held its limits when switching on and changing
  mode, which no simulation can tell.
* Screw terminals or solder, not crocodile clips: a contact that drops
  and comes back mid-sweep is a surge.

A facet can fail suddenly, before its curve bends: the light ceiling is
the guard that matters, the curve a second one.

Stages (`--stages`, default all, in this order):

1. **dark**: the photodiode with the laser off, 2 s after channel 2 is
   set up; refused if more than 20 uA from 0, and read again at 0 mA
   before and after the current sweep (an offset is not light).
2. **current**: current forced up until a stop above, then back down
   over the same levels: light against current (threshold, slope, kinks,
   up/down hysteresis) and the voltage it needs. This is how the new
   board would drive it.
3. **voltage**: for a module that lases, voltage forced from 0 to 5.5 V
   under a limit that keeps the plain-diode curve below the light
   ceiling (or the highest current reached, if the curve bent): light
   and current against supply voltage, as the new board would drive it.
   A dummy load to the voltage at 80 % of its highest current.
4. **hold**: `--hold-s` at that voltage, dark for `--gap-s`, then
   `--hold-s` at that current: which keeps the light steadier.

The report has every reading; a PNG of the curves is written next to it.
"""

from __future__ import annotations

import statistics
import sys
from dataclasses import asdict, dataclass

from multilbic.bench.report import (
    Report,
    base_parser,
    linear_fit,
    say,
    setup,
    summary,
)
from multilbic.hardware.smu import PhotocurrentSmu, open_smu

#: Absolute ceilings, whatever the arguments say. The miniSMU itself
#: does 12 V, 180 mA and 2.1 W a channel.
MAX_MW = 5.0
MAX_V = 5.5
MAX_I_A = 0.12
MAX_W = 1.0
#: The share of the light ceiling the photodiode may read before the
#: sweep stops: margin for under-reading a small spot.
MARGIN_CALIBRATED = 0.8
MARGIN_DATASHEET = 0.65
#: Light must be seen by this times --i-known.
LIGHT_BY = 1.5
#: Channel 1 measures on the 180 mA range throughout; channel 2 on the
#: fixed 15 mA range. Autoranging, the miniSMU holds a channel to 1 mA
#: whatever limit is set (hardware/smu.md), under every light ceiling:
#: laser 4's first run read its light flat at 1.01 mA (2026-11-10).
LASER_RANGE_A = 0.18
PD_LIMIT_A = 15e-3
#: A photodiode reading this close to its range's end is clipped.
PD_CLIPPED = 0.9
#: Light this far from dark counts as lit (or 10 x the dark's scatter,
#: if more: the 15 mA range is coarser than autorange).
LIT_A = 0.5e-6
LIT_SCATTER = 10.0
#: The dark: read this long after channel 2 is set up, never further
#: from 0 than DARK_MAX_A (room light is uA at most), and the photodiode
#: back within DARK_STEADY_A of it whenever channel 1 is at 0 mA. Laser
#: 4's second run read +297 uA dark for its first second on the 15 mA
#: range, -0.25 uA after (2026-11-10): its light was all offset.
DARK_SETTLE_S = 2.0
DARK_MAX_A = 20e-6
DARK_STEADY_A = 2e-6
#: Channel 2 must report its 0 V within this. Setting channel 1's mode
#: puts channel 2 in its offset state (+0.30 V reported, +2 % of each
#: range's full scale read) until channel 1's range is set again
#: (bench, 2026-11-10; hardware/smu.md).
PD_V_MAX = 0.01
#: Current steps: never below MIN_STEP_A; stop this close to the ceiling.
MIN_STEP_A = 20e-6
CREEP_STOP = 0.02
#: The curve bends: slope over the last BEND_SPAN_A below BEND x its best,
#: once the light is past BEND_FROM of the ceiling (noise below that).
BEND = 0.85
BEND_SPAN_A = 1e-3
BEND_FROM = 0.05
#: Light falling by more than this share between steps.
FALL = 0.01
#: A regulator's knee: the volts per amp over the last step past KNEE x
#: their median over the KNEE_SPAN_A before it, and past KNEE_MIN_OHM.
#: Laser 4's regulator: 25 ohm to 22 mA, then 530 and 1900 (2026-11-10).
KNEE = 8.0
KNEE_SPAN_A = 1e-3
KNEE_MIN_OHM = 200.0
#: A driver switching on: forced past it, the current at the voltage
#: limit falls below this share of the last current before (laser 3:
#: 22.5 mA, then 16.6 mA at 5.5 V, 2026-11-10).
SWITCHED = 0.9
#: A regulated module's voltage sweep goes to MAX_V under a current
#: limit that keeps the light, as the plain-diode curve rises, this
#: share of the way from the light reached to the ceiling; and may sit
#: at that limit this far past where it first did.
SWEEP_LIGHT_SHARE = 0.9
SWEEP_AT_LIMIT_V = 0.5
#: After a curve that bent, the voltage sweep's limit is at most this
#: times the highest current reached (laser 5's bend was its light per
#: mA easing from 87 to 74 uA; its driver takes over above that).
BENT_SWEEP = 1.5
#: Voltages the verdict quotes from a regulated module's voltage sweep.
QUOTE_V = (3.3, 5.0)
#: A reading this close to a limit is the limit.
AT_LIMIT = 0.97
#: The operating point for the voltage stage and the holds.
OPERATING = 0.8
STAGES = ("dark", "current", "voltage", "hold")
POLARITY_V = 1.0
POLARITY_LIMIT_A = 1e-3


class StopRun(Exception):
    """A reason not to go on: channel 1 goes off."""


@dataclass
class Point:
    set: float  # volts or amps, as forced
    v: float
    i: float
    pd: float
    #: Why the sweep stopped here, or "".
    why: str = ""
    t: float = 0.0


@dataclass(frozen=True)
class Caps:
    i_a: float
    #: Light above dark the photodiode may read; None on a dummy load.
    light_a: float | None


class ModuleRig:
    """Channel 1 drives the module, channel 2 reads the photodiode."""

    def __init__(self, smu: PhotocurrentSmu, clock, reads: int, settle_s: float):
        self.smu = smu
        self.clock = clock
        self.reads = reads
        self.settle_s = settle_s
        self.dark = 0.0
        self.lit_a = LIT_A
        #: Channel 2's voltage over the last read: 0 V unless offset.
        self.pd_v = 0.0
        #: Points whose bend or fall was read again (and didn't hold).
        self.read_again: list[Point] = []
        self.laser = smu.drivers[1]
        self.pd = smu.drivers[2]
        self.client = smu.stream._client
        self.mode = "off"

    def start(self) -> None:
        """Both channels reset (outputs off), the photodiode on at 0 V
        on the fixed 15 mA range."""
        for driver in (self.laser, self.pd):
            driver.reset()
        # Each channel: mode, range, then limits and level. A range
        # command sets the current limit to the range's full scale, so a
        # limit set before it is lost (laser 5's voltage sweep, 18.76 mA
        # through a 15.5 mA limit, 2026-11-10).
        self.pd.set_source_function("voltage")
        self.client.set_current_range_by_limit(2, PD_LIMIT_A, disable_autorange=True)
        self.pd.set_current_limit(PD_LIMIT_A)
        self.pd.set_voltage_level(0.0)
        # Channel 1 parked, output off: current mode at 0 A. Its range
        # after its mode clears channel 2's offset state (PD_V_MAX).
        self.laser.set_source_function("current")
        self._fix_range()
        self.laser.set_voltage_limit(MAX_V)
        self.laser.set_current_level(0.0)
        self.mode = "off"
        self.pd.output_on()

    def off(self) -> None:
        """Channel 1 to zero, then off. Safe to call at any time."""
        if self.mode == "voltage":
            self.laser.set_voltage_level(0.0)
        elif self.mode == "current":
            self.laser.set_current_level(0.0)
        self.laser.output_off()
        self.mode = "off"

    def force_voltage(self, current_limit_a: float) -> None:
        """Voltage mode at 0 V, the current limit set before output on."""
        self.off()
        self.laser.set_source_function("voltage")
        self._fix_range()
        self.laser.set_current_limit(min(current_limit_a, MAX_I_A))
        self.laser.set_voltage_level(0.0)
        self.laser.output_on()
        self.mode = "voltage"

    def force_current(self, voltage_limit_v: float) -> None:
        """Current mode at 0 A, the voltage limit set before output on."""
        self.off()
        self.laser.set_source_function("current")
        self._fix_range()
        self.laser.set_voltage_limit(min(voltage_limit_v, MAX_V))
        self.laser.set_current_level(0.0)
        self.laser.output_on()
        self.mode = "current"

    def _fix_range(self) -> None:
        self.client.set_current_range_by_limit(
            1, LASER_RANGE_A, disable_autorange=True
        )

    def set(self, level: float) -> None:
        if level < 0:
            raise ValueError("never a negative level: that is reverse bias")
        if self.mode == "voltage":
            self.laser.set_voltage_level(min(level, MAX_V))
        elif self.mode == "current":
            self.laser.set_current_level(min(level, MAX_I_A))
        else:
            raise RuntimeError("channel 1 is off")

    def read(self, reads: int | None = None) -> tuple[float, float, float]:
        """Mean (volts, amps) on the module and amps on the photodiode."""
        n = reads or self.reads
        vs, is_, pds, pd_vs = [], [], [], []
        for _ in range(n):
            v, i = self.laser.measure() if self.mode != "off" else (0.0, 0.0)
            pd_v, pd = self.pd.measure()
            pds.append(pd)
            pd_vs.append(pd_v)
            vs.append(v)
            is_.append(i)
        self.pd_v = statistics.fmean(pd_vs)
        return statistics.fmean(vs), statistics.fmean(is_), statistics.fmean(pds)

    def check_pd_voltage(self) -> None:
        if abs(self.pd_v) > PD_V_MAX:
            raise StopRun(
                f"channel 2 reports {self.pd_v:+.3f} V where it holds 0 V: its "
                f"offset state (hardware/smu.md), so the photodiode reads high"
            )

    def light(self, pd: float) -> float:
        return abs(pd - self.dark)

    def check(self, v: float, i: float, pd: float, caps: Caps) -> None:
        """End the run if an absolute ceiling did not hold."""
        self.check_pd_voltage()
        if abs(i) > caps.i_a * 1.03 + 0.2e-3:
            raise StopRun(
                f"{i * 1e3:.2f} mA read against a {caps.i_a * 1e3:.1f} mA ceiling: "
                f"the limit did not hold"
            )
        if v > MAX_V * 1.03 + 0.05:
            raise StopRun(f"{v:.2f} V read against {MAX_V} V: the limit did not hold")
        if v * abs(i) > MAX_W:
            raise StopRun(f"{v * abs(i):.2f} W at {v:.2f} V, {i * 1e3:.1f} mA")
        if abs(pd) > PD_CLIPPED * PD_LIMIT_A:
            raise StopRun(
                f"photodiode {abs(pd) * 1e3:.2f} mA, at its range's end: "
                f"the light can't be read"
            )
        if caps.light_a is not None and self.light(pd) > caps.light_a * 1.1:
            raise StopRun(
                f"light {self.light(pd) * 1e6:.0f} uA against a "
                f"{caps.light_a * 1e6:.0f} uA ceiling"
            )

    def step(self, level: float, caps: Caps) -> Point:
        self.set(level)
        self.clock.sleep(self.settle_s)
        v, i, pd = self.read()
        self.check(v, i, pd, caps)
        return Point(level, v, i, pd, "", self.clock.now())


# ---- stages ----


def stage_dark(rig: ModuleRig, report: Report) -> None:
    rig.off()
    rig.clock.sleep(DARK_SETTLE_S)
    pds = []
    for _ in range(20):
        pds.append(rig.read(1)[2])
        rig.check_pd_voltage()
    rig.dark = statistics.fmean(pds)
    scatter = statistics.stdev(pds)
    rig.lit_a = max(LIT_A, LIT_SCATTER * scatter)
    report["dark"] = {"pd_a": summary(pds), "pd_range_a": PD_LIMIT_A,
                      "lit_a": rig.lit_a}
    say(f"dark: photodiode {rig.dark:+.3e} A, stdev {scatter:.1e} A "
        f"(15 mA range); lit above {rig.lit_a * 1e6:.2f} uA")
    if abs(rig.dark) > DARK_MAX_A:
        raise StopRun(
            f"the photodiode reads {rig.dark * 1e6:+.1f} uA with the laser off: "
            f"an offset, not light (hardware/smu.md, the channel-2 offset "
            f"state). Run it again; if it stays, switch the miniSMU off and on"
        )


def check_dark(rig: ModuleRig, p: Point, when: str) -> None:
    """Channel 1 at 0 mA: the photodiode must read its dark again."""
    off_by = abs(p.pd - rig.dark)
    if off_by > max(DARK_STEADY_A, rig.lit_a):
        raise StopRun(
            f"{when}, channel 1 at 0 mA, the photodiode reads "
            f"{off_by * 1e6:.1f} uA from its dark: the dark isn't steady, "
            f"so the light can't be trusted"
        )


def _slope(points: list[Point], rig: ModuleRig) -> float | None:
    """Light per amp over the last BEND_SPAN_A of current."""
    window = [points[-1]]
    for p in reversed(points[:-1]):
        window.insert(0, p)
        if points[-1].i - p.i >= BEND_SPAN_A and len(window) >= 3:
            break
    if len(window) < 3 or window[-1].i - window[0].i < 0.5 * BEND_SPAN_A:
        return None
    slope, _ = linear_fit([p.i for p in window], [rig.light(p.pd) for p in window])
    return slope


def knee(iv: list[tuple[float, float]]) -> float | None:
    """How many times steeper the last step's volts per amp are than
    the steps over KNEE_SPAN_A before it, if that is a regulator's knee;
    else None. `iv` is (amps, volts) as measured, in sweep order."""
    steps = [
        (b[0], (b[1] - a[1]) / (b[0] - a[0]))
        for a, b in zip(iv, iv[1:], strict=False)
        if b[0] - a[0] > 5e-6
    ]
    if len(steps) < 3:
        return None
    end, last = steps[-1]
    before = [r for i, r in steps[:-1] if i > end - KNEE_SPAN_A - 1e-9]
    if len(before) < 2:
        return None
    reference = statistics.median(before)
    if reference <= 0 or last < KNEE_MIN_OHM or last < KNEE * reference:
        return None
    return last / reference


def current_up(rig: ModuleRig, caps: Caps, args) -> list[Point]:
    """Current up from 0 until a stop; see the module's docstring."""
    dummy = caps.light_a is None
    light_cap = caps.light_a or 0.0
    light_by = LIGHT_BY * args.i_known
    points: list[Point] = []
    best = 0.0
    level = 0.0
    again = False
    rig.force_current(MAX_V)
    while True:
        p = rig.step(level, caps)
        points.append(p)
        say(_point_line(p, rig.dark))
        if level == 0:
            check_dark(rig, p, "before the sweep")
        light = rig.light(p.pd)
        lit = light > rig.lit_a
        slope = None if dummy else _slope(points, rig)
        if p.v >= AT_LIMIT * MAX_V or p.i < level - (0.03 * level + 50e-6):
            p.why = "voltage limit"
        elif level >= caps.i_a:
            p.why = "current ceiling"
        elif knee([(q.i, q.v) for q in points]) is not None:
            p.why = "regulator"
        elif dummy:
            pass
        elif light >= light_cap * (1 - CREEP_STOP):
            p.why = "light ceiling"
        elif not lit and level >= light_by:
            raise StopRun(
                f"no light by {level * 1e3:.1f} mA ({LIGHT_BY:g} x --i-known): "
                f"is the beam parked on the photodiode?"
            )
        elif len(points) >= 2 and lit and light < (1 - FALL) * rig.light(points[-2].pd) - rig.lit_a:
            p.why = "light fell"
        elif slope is not None and light > BEND_FROM * light_cap:
            best = max(best, slope)
            if slope < BEND * best:
                p.why = "curve bending"
        if p.why in ("light fell", "curve bending") and not again:
            # Once more at the same current, no higher: laser 5's light
            # dipped up to 6 % at random, and one dip read as a bend.
            say(f"  {p.why}? reading it again")
            rig.read_again.append(points.pop())
            again = True
            continue
        if p.why:
            say(f"  {p.why}: turning back")
            return points
        again = False
        step = args.i_step
        if not dummy and lit and slope and slope > 0:
            step = min(step, 0.5 * (light_cap - light) / slope)
        level = min(level + max(step, MIN_STEP_A), caps.i_a)


def stage_current(rig, report, args, caps: Caps) -> dict:
    say(
        f"current: up in {args.i_step * 1e3:g} mA steps to a stop, then back; "
        f"ceilings {caps.i_a * 1e3:.0f} mA, {MAX_V} V"
        + (f", {caps.light_a * 1e6:.0f} uA of light" if caps.light_a else "")
    )
    up = current_up(rig, caps, args)
    down = [rig.step(p.set, caps) for p in reversed(up[:-1])]
    rig.off()
    result = {
        "up": [asdict(p) for p in up],
        "down": [asdict(p) for p in down],
        "stopped_by": up[-1].why,
        "read_again": [asdict(p) for p in rig.read_again],
    }
    report["current"] = result
    if down and down[-1].set == 0:
        check_dark(rig, down[-1], "after the sweep")
    return result


def _between(points: list[dict], key: str, target: float, out: str) -> float | None:
    """`out` where `key` first reaches `target` (interpolated)."""
    for a, b in zip(points, points[1:], strict=False):
        if a[key] <= target <= b[key]:
            if b[key] == a[key]:
                return a[out]
            return a[out] + (b[out] - a[out]) * (target - a[key]) / (b[key] - a[key])
    return None


def operating_point(up: list[dict], dark: float = 0.0,
                    lit_a: float = LIT_A) -> tuple[float, float, float]:
    """(current, voltage, highest current) for the later stages: where
    the light reached 80 % of its peak before the stop, and the voltage
    the module needed there (interpolated). With no light (a dummy
    load), 80 % of the highest current. Not 80 % of the current: laser
    4 lases from 16.5 mA and stopped at 20.5, so that put its holds
    below threshold (2026-11-10)."""
    good = [p for p in up if not p["why"]] or up[:1]
    i_max = max(p["i"] for p in good)
    lit = [dict(p, light=abs(p["pd"] - dark)) for p in good]
    peak = max(p["light"] for p in lit)
    i_op = None
    if peak > lit_a:
        i_op = _between(lit, "light", OPERATING * peak, "i")
    if i_op is None:
        i_op = OPERATING * i_max
    v = _between(good, "i", i_op, "v")
    return i_op, good[-1]["v"] if v is None else v, i_max


def prove_current_limit(rig, report, judged: dict, up: list[dict], caps: Caps) -> None:
    """Channel 1's current limit, proven on the instrument before the
    voltage sweep relies on it: the voltage that drew half the lasing
    threshold (or half the highest current, with no light), under a
    limit of half that. Held, it reads the limit; not held, the module
    takes that current, below threshold, and the run stops."""
    good = [p for p in up if not p["why"]]
    i_max = max((p["i"] for p in good), default=0.0)
    threshold = judged.get("threshold_a")
    target = 0.5 * threshold if threshold and threshold > 2e-3 else 0.5 * i_max
    volts = _between(good, "i", target, "v")
    if volts is None or target < 1e-3:
        report["limit_check"] = {"skipped": "no point to check from"}
        return
    limit = 0.5 * target
    say(f"limit check: {volts:.2f} V (drew {target * 1e3:.1f} mA) under a "
        f"{limit * 1e3:.1f} mA limit")
    rig.force_voltage(limit)
    caps_check = Caps(limit, caps.light_a)
    for k in range(1, 4):
        p = rig.step(volts * k / 3, caps_check)
    rig.off()
    report["limit_check"] = {"v": volts, "limit_a": limit, "read_a": p.i,
                             "unlimited_a": target}
    say(f"limit check: {p.i * 1e3:.2f} mA read: the limit holds")


def sweep_limit(judged: dict, caps: Caps, i_max: float) -> float:
    """The current limit for the voltage sweep: where the plain-diode
    curve, straight to its end, would put the light SWEEP_LIGHT_SHARE of
    the way from the light reached to the ceiling. A voltage sweep has
    to pass the current where a driver takes over (laser 3's, past
    22.5 mA; laser 5's, past 16). After a bend, no more than BENT_SWEEP
    times the highest current reached; after a fall, that current."""
    limit = i_max
    slope = judged.get("slope_a_per_a")
    peak = judged.get("diode_peak_light_a")
    if caps.light_a and slope and slope > 0 and peak is not None:
        room = max(0.0, caps.light_a - peak)
        limit = i_max + SWEEP_LIGHT_SHARE * room / slope
    if judged.get("stopped_by") == "light fell":
        limit = i_max
    elif judged.get("stopped_by") == "curve bending":
        limit = min(limit, BENT_SWEEP * i_max)
    return min(limit, caps.i_a)


def stage_voltage(rig, report, args, caps: Caps, v_op, i_max,
                  judged: dict | None = None) -> dict:
    """Voltage forced up: for a module that lases, to MAX_V, the module
    on a plain supply as the new board would drive it (a dummy load to
    the operating point's voltage)."""
    regulated = (caps.light_a is not None
                 and (judged or {}).get("peak_light_a", 0.0) > LIT_A)
    top = MAX_V if regulated else v_op
    i_limit = sweep_limit(judged or {}, caps, i_max) if regulated else min(i_max, caps.i_a)
    limit = Caps(i_limit, caps.light_a)
    say(f"voltage: 0 -> {top:.2f} V, limit {i_limit * 1e3:.1f} mA")
    rig.force_voltage(limit.i_a)
    n = max(1, round(top / args.v_step))
    points = []
    limited_from = None
    for k in range(n + 1):
        level = top * k / n
        p = rig.step(level, limit)
        at_limit = abs(p.i) >= AT_LIMIT * limit.i_a
        if at_limit and limited_from is None:
            limited_from = level
        elif not at_limit:
            limited_from = None
        if at_limit and (not regulated or level - limited_from >= SWEEP_AT_LIMIT_V):
            p.why = "current limit"
        elif caps.light_a and rig.light(p.pd) >= caps.light_a * (1 - CREEP_STOP):
            p.why = "light ceiling"
        points.append(p)
        say(_point_line(p, rig.dark))
        if p.why:
            break
    rig.off()
    result = {
        "to_v": top,
        "current_limit_a": limit.i_a,
        "points": [asdict(p) for p in points],
        "stopped_by": points[-1].why if points else "",
    }
    report["voltage"] = result
    return result


def hold(rig, seconds, every_s, caps) -> list[Point]:
    points = []
    start = rig.clock.now()
    while rig.clock.now() - start < seconds:
        v, i, pd = rig.read(1)
        rig.check(v, i, pd, caps)
        points.append(Point(0.0, v, i, pd, "", rig.clock.now() - start))
        rig.clock.sleep(every_s)
    return points


def ramp(rig, level, caps, steps=5) -> None:
    for k in range(1, steps + 1):
        rig.step(level * k / steps, caps)


def stage_hold(rig, report, args, caps: Caps, i_op, v_op, i_max,
               voltage: dict | None = None) -> dict:
    """At a voltage, then at a current. For a regulated module whose
    voltage sweep passed today's voltage (--v-known), at that voltage,
    on its own regulator, under that sweep's limit."""
    limit = Caps(min(i_max, caps.i_a), caps.light_a)
    if voltage and voltage.get("to_v", 0) >= MAX_V and args.v_known:
        reached = max((p["v"] for p in voltage["points"]), default=0.0)
        if args.v_known <= reached:
            v_op = args.v_known
            limit = Caps(voltage["current_limit_a"], caps.light_a)
    say(f"hold: {args.hold_s:g} s at {v_op:.2f} V (limit {limit.i_a * 1e3:.1f} mA)")
    rig.force_voltage(limit.i_a)
    ramp(rig, v_op, limit)
    by_voltage = hold(rig, args.hold_s, args.every_s, limit)
    rig.off()
    rig.clock.sleep(args.gap_s)
    say(f"hold: {args.hold_s:g} s at {i_op * 1e3:.1f} mA")
    rig.force_current(MAX_V)
    ramp(rig, i_op, limit)
    by_current = hold(rig, args.hold_s, args.every_s, limit)
    rig.off()
    result = {
        "constant_voltage": {"v": v_op, "points": [asdict(p) for p in by_voltage]},
        "constant_current": {"a": i_op, "points": [asdict(p) for p in by_current]},
        "gap_s": args.gap_s,
    }
    report["hold"] = result
    return result


# ---- what the readings say ----


def judge_current(up: list[dict], down: list[dict], dark: float, response: float | None) -> dict:
    stop = up[-1]["why"]
    good = [p for p in up if not p["why"]]
    out: dict = {"stopped_by": stop}
    if len(good) < 3:
        out["kind"] = "too few points"
        return out
    out["i_max_a"] = max(p["i"] for p in good)
    out["v_at_max"] = good[-1]["v"]
    switched = (stop == "voltage limit" and good[-1]["v"] < MAX_V - 0.3
                and up[-1]["i"] < SWITCHED * good[-1]["i"])
    if switched:
        # Forced past it, the voltage jumped to the limit and the current
        # fell: a driver inside switched on (laser 3).
        out["kind"] = "driver"
        out["i_switch_a"] = good[-1]["i"]
        out["v_switch"] = good[-1]["v"]
        out["i_after_a"] = up[-1]["i"]
        out["v_after"] = up[-1]["v"]
        out["light_after_a"] = abs(up[-1]["pd"] - dark)
        if response:
            out["mw_after"] = out["light_after_a"] / response * 1e3
    elif stop == "regulator" or (stop == "voltage limit" and good[-1]["v"] < MAX_V - 0.3):
        # The voltage climbed steeply (a knee), or jumped to the limit
        # from well below it: a regulator took over.
        out["kind"] = "regulated"
        out["i_reg_a"] = up[-1]["i"]
        out["v_reg"] = good[-1]["v"]
        out["v_at_reg"] = up[-1]["v"]
        out["regulated_light_a"] = abs(up[-1]["pd"] - dark)
        if response:
            out["regulated_mw"] = out["regulated_light_a"] / response * 1e3
    elif stop == "voltage limit":
        out["kind"] = "needs more than the voltage limit"
    else:
        out["kind"] = "no regulator reached"
    light = [abs(p["pd"] - dark) for p in good]
    out["diode_peak_light_a"] = max(light)
    peak = max(light + [out.get("regulated_light_a", 0.0), out.get("light_after_a", 0.0)])
    out["peak_light_a"] = peak
    if response:
        out["peak_mw"] = peak / response * 1e3
    if peak < LIT_A:
        return out
    upper = [(p["i"], li) for p, li in zip(good, light, strict=True) if li >= 0.2 * max(light)]
    if len(upper) >= 2:
        slope, intercept = linear_fit([u[0] for u in upper], [u[1] for u in upper])
        out["slope_a_per_a"] = slope
        out["threshold_a"] = -intercept / slope if slope else None
        if response:
            out["slope_mw_per_ma"] = slope / response
    tolerance = max(FALL * peak, LIT_A)
    out["kinks"] = sum(1 for a, b in zip(light, light[1:], strict=False) if b < a - tolerance)
    # Up against down at each level, on the same branch only: down
    # points far from the up point's voltage are a driver still on.
    by_set = {round(p["set"], 9): p for p in good}
    gaps, still_on = [], []
    for p in down:
        u = by_set.get(round(p["set"], 9))
        if u is None:
            continue
        if abs(p["v"] - u["v"]) > 0.2:
            still_on.append(p["set"])
            continue
        gaps.append(abs(abs(p["pd"] - dark) - abs(u["pd"] - dark)))
    out["hysteresis_fraction"] = max(gaps) / max(light) if gaps else None
    if still_on:
        out["down_still_switched_to_a"] = min(still_on)
    return out


def current_at_voltage(up: list[dict], volts: float) -> float | None:
    """The current the module took at `volts`, from the current sweep
    (its regulator's knee included)."""
    good = [p for p in up if p["why"] in ("", "regulator")]
    for a, b in zip(good, good[1:], strict=False):
        if a["v"] <= volts <= b["v"] and b["v"] > a["v"]:
            return a["i"] + (b["i"] - a["i"]) * (volts - a["v"]) / (b["v"] - a["v"])
    return None


def judge_hold(points: list[dict], dark: float) -> dict | None:
    if len(points) < 6:
        return None
    light = [abs(p["pd"] - dark) for p in points]
    if statistics.fmean(light) < LIT_A:
        return None  # no light to drift (a dummy load)
    n = max(1, len(light) // 10)
    first, last = statistics.fmean(light[:n]), statistics.fmean(light[-n:])
    return {
        "first_a": first,
        "last_a": last,
        "drift_percent": (last / first - 1) * 100,
        "spread_percent": (max(light) - min(light)) / statistics.fmean(light) * 100,
    }


def judge_voltage(points: list[dict], dark: float, response: float | None,
                  quote: tuple[float, ...]) -> dict | None:
    """A regulated module on a plain supply: where it switched over, and
    current and light at the voltages quoted."""
    good = [p for p in points if not p["why"]] or points
    if len(good) < 3:
        return None
    out: dict = {"top_v": max(p["v"] for p in good),
                 "stopped_by": points[-1]["why"] if points else ""}
    peak = max(good, key=lambda p: p["i"])
    out["peak_a"], out["peak_v"] = peak["i"], peak["v"]
    out["peak_light_a"] = abs(peak["pd"] - dark)
    after = [p for p in good if p["v"] > peak["v"]]
    if after:
        low = min(after, key=lambda p: p["i"])
        if low["i"] < SWITCHED * peak["i"]:
            # Its current falls as the voltage rises: a driver taking over.
            settled = next(p for p in after if p["i"] <= low["i"] * 1.02)
            out["handover_to_a"], out["handover_v"] = low["i"], settled["v"]
    for a, b in zip(good, good[1:], strict=False):
        if b["i"] < SWITCHED * a["i"] and a["i"] > 1e-3:
            out["switch_v"] = b["v"]
            out["switch_from_a"], out["switch_to_a"] = a["i"], b["i"]
            break
    at: dict[str, dict] = {}
    for volts in quote:
        near = min(good, key=lambda p: abs(p["v"] - volts))
        if abs(near["v"] - volts) <= 0.06:
            light = abs(near["pd"] - dark)
            at[f"{volts:.2f}"] = {
                "v": near["v"], "a": near["i"], "light_a": light,
                "mw": light / response * 1e3 if response else None,
            }
    out["at"] = at
    return out


def verdict(results: dict, args) -> list[str]:
    lines: list[str] = []
    if results.get("dummy_load"):
        return [_dummy_summary(results, args)]
    c = results.get("judged_current")
    if not c or c.get("kind") == "too few points":
        return lines
    mw = c.get("peak_mw")
    mw_text = f" ({mw:.2f} mW as it reads)" if mw is not None else ""
    if c["kind"] == "driver":
        mw_after = c.get("mw_after")
        lines.append(
            f"A driver inside: a plain diode up to {c['i_switch_a'] * 1e3:.1f} mA "
            f"({c['v_switch']:.2f} V); forced past it, the voltage jumped to "
            f"{c['v_after']:.2f} V and the current fell to {c['i_after_a'] * 1e3:.1f} mA "
            f"with {c['light_after_a'] * 1e6:.0f} uA of light"
            + (f" ({mw_after:.2f} mW)" if mw_after is not None else "")
            + ", more than that current gives it as a diode"
            + (f"; it stayed switched down to {c['down_still_switched_to_a'] * 1e3:.1f} mA."
               if c.get("down_still_switched_to_a") else ".")
        )
    elif c["kind"] == "regulated":
        held = ""
        if c.get("regulated_light_a"):
            mw_reg = c.get("regulated_mw")
            held = (f", holding {c['regulated_light_a'] * 1e6:.0f} uA on the photodiode"
                    + (f" ({mw_reg:.2f} mW)" if mw_reg is not None else ""))
        lines.append(
            f"Regulated inside: from {c['i_reg_a'] * 1e3:.1f} mA its voltage climbs "
            f"steeply ({c['v_reg']:.2f} V just below, {c['v_at_reg']:.2f} V at it): "
            f"its own regulator takes over there{held}. At {c['v_at_reg']:.2f} V or "
            f"more it sets its own power; the board can dim it by holding it "
            f"below {c['i_reg_a'] * 1e3:.1f} mA."
        )
    elif c["kind"] == "needs more than the voltage limit":
        lines.append(
            f"Reached {MAX_V} V at {c['i_max_a'] * 1e3:.1f} mA, still taking more: "
            f"a regulator wanting more than {MAX_V} V, or a diode needing it."
        )
    else:
        lines.append(
            f"No regulator up to {c['i_max_a'] * 1e3:.1f} mA, where the "
            f"{c['stopped_by']} stopped it: the board's current sets its power."
        )
    if "threshold_a" in c and c["threshold_a"]:
        slope = (f", {c['slope_mw_per_ma']:.3f} mW per mA"
                 if "slope_mw_per_ma" in c else "")
        smooth = "smoothly" if not c["kinks"] else f"with {c['kinks']} kink(s)"
        lines.append(
            f"Light follows current {smooth} from a threshold of "
            f"{c['threshold_a'] * 1e3:.1f} mA{slope}, up to "
            f"{c['peak_light_a'] * 1e6:.0f} uA on the photodiode{mw_text}."
        )
    vj = results.get("judged_voltage")
    if vj:
        text = f"On a plain supply (voltage forced to {vj['top_v']:.2f} V)"
        if "switch_v" in vj:
            text += (f", it switched over at {vj['switch_v']:.2f} V (current "
                     f"{vj['switch_from_a'] * 1e3:.1f} -> {vj['switch_to_a'] * 1e3:.1f} mA)")
        elif "handover_to_a" in vj:
            text += (f", its current peaks at {vj['peak_a'] * 1e3:.1f} mA at "
                     f"{vj['peak_v']:.2f} V ({vj['peak_light_a'] * 1e6:.0f} uA) and falls "
                     f"to {vj['handover_to_a'] * 1e3:.1f} mA by {vj['handover_v']:.2f} V, "
                     f"its driver taking over")
        elif vj.get("stopped_by") == "current limit":
            text += (f", it reached the sweep's current limit at "
                     f"{vj['top_v']:.2f} V: no driver took over")
        quoted = [
            f"at {q['v']:.2f} V {q['a'] * 1e3:.1f} mA for {q['light_a'] * 1e6:.0f} uA"
            + (f" ({q['mw']:.2f} mW)" if q.get("mw") is not None else "")
            for q in vj["at"].values()
        ]
        lines.append(text + (": " + "; ".join(quoted) if quoted else "") + ".")
    if c["kind"] == "driver":
        lines.append(
            "For the board: a fixed voltage, not a current. Near its switching "
            "current it has two states, as a diode or on its driver, and a "
            "current limit can leave it in either."
        )
    elif c["kind"] == "regulated":
        lines.append(
            f"For the board: at least {c['v_at_reg']:.2f} V at the module for its "
            f"own power, so about {c['v_at_reg'] + 1.0:.1f} V of rail (1 V for the "
            f"switch or a dimming regulator)."
        )
    else:
        lines.append(
            f"For the board: up to {c['i_max_a'] * 1e3:.0f} mA at {c['v_at_max']:.2f} V, "
            f"so about {c['v_at_max'] + 1.0:.1f} V of rail (1 V for the regulator)."
        )
    if args.v_known is not None and "current" in results:
        today = current_at_voltage(results["current"]["up"], args.v_known)
        if today is not None:
            lines.append(
                f"Today's {args.v_known:.2f} V gives it about {today * 1e3:.1f} mA "
                f"of the {c['i_max_a'] * 1e3:.1f} mA reached here."
            )
    if c.get("hysteresis_fraction") is not None:
        lines.append(
            f"Up and down differ by up to {c['hysteresis_fraction'] * 100:.1f} % "
            f"of the peak light."
        )
    h = results.get("judged_hold") or {}
    cv, cc = h.get("constant_voltage"), h.get("constant_current")
    if cv and cc:
        lines.append(
            f"Over {args.hold_s:g} s the light moved {cv['drift_percent']:+.1f} % at "
            f"constant voltage and {cc['drift_percent']:+.1f} % at constant current."
        )
    return lines


def _every_reading(results: dict) -> list[dict]:
    readings = list(results.get("current", {}).get("up", []))
    readings += results.get("current", {}).get("down", [])
    readings += results.get("voltage", {}).get("points", [])
    for key in ("constant_voltage", "constant_current"):
        readings += results.get("hold", {}).get(key, {}).get("points", [])
    return readings


def _dummy_summary(results: dict, args) -> str:
    """The dry run's point: did every reading stay under the ceilings?"""
    readings = _every_reading(results)
    v_max = max((p["v"] for p in readings), default=0.0)
    i_max = max((abs(p["i"]) for p in readings), default=0.0)
    cap = results["ceilings"]["current_a"]
    held = v_max <= MAX_V * 1.03 + 0.05 and i_max <= cap * 1.03 + 0.2e-3
    voltage = results.get("voltage", {})
    if voltage:
        held = held and max(abs(p["i"]) for p in voltage["points"]) <= (
            voltage["current_limit_a"] * 1.03 + 0.2e-3
        )
    return (
        f"Dummy load: highest {v_max:.2f} V (limit {MAX_V} V) and "
        f"{i_max * 1e3:.2f} mA over {len(readings)} readings: "
        + ("the limits held." if held else "THE LIMITS DID NOT HOLD: no laser on this.")
    )


# ---- plumbing ----


def parse_amps(text: str) -> float:
    """'0.032', '32m', '32mA', '32 mA' -> amps."""
    t = text.strip().lower().removesuffix("a").strip()
    scale = {"m": 1e-3, "u": 1e-6}.get(t[-1:], 1.0)
    if scale != 1.0:
        t = t[:-1]
    return float(t) * scale


def _point_line(p: Point, dark: float) -> str:
    return (
        f"  {p.v:6.3f} V  {p.i * 1e3:8.3f} mA  "
        f"light {abs(p.pd - dark) * 1e6:10.3f} uA"
    )


def _open(args, clock) -> PhotocurrentSmu:
    if args.sim:
        from multilbic.sim.fake_smu import FakeMiniSMUTransport
        from multilbic.sim.laser_module import FakeModuleSMU, module

        fake = FakeModuleSMU(clock, module("dummy" if args.dummy_load else args.module))
        return PhotocurrentSmu(FakeMiniSMUTransport(fake), clock, (1, 2))
    return open_smu(args.port, clock, (1, 2))


def light_ceiling(args, machine) -> tuple[float | None, float | None, str]:
    """(photodiode amps to stop at, its response A/W, where that came from)."""
    if args.dummy_load:
        return None, None, "dummy load: no light"
    from multilbic.scan.eqe import datasheet_response

    laser = machine.laser(args.laser)
    if laser.pd_response_a_w and not args.datasheet_response:
        response, margin = laser.pd_response_a_w, MARGIN_CALIBRATED
        source = f"power meter {laser.pd_response_date or ''}".strip()
    else:
        response = datasheet_response(laser.wavelength_nm)
        margin = MARGIN_DATASHEET
        source = "S1223-01 datasheet"
    return margin * args.max_mw * 1e-3 * response, response, source


def _check_args(parser, args, machine) -> None:
    if args.polarity_check:
        return
    if args.sim and args.laser is None and not args.dummy_load:
        args.laser = 3
    if args.sim and args.i_known is None:
        from multilbic.sim.laser_module import module

        args.i_known = module("dummy" if args.dummy_load else args.module).i_known
    if args.dummy_load and args.laser:
        parser.error("--dummy-load is a resistor, not laser --laser")
    if args.i_known is None:
        parser.error("--i-known is needed: the current on the laser board today")
    if not args.dummy_load:
        if args.laser is None:
            parser.error("--laser is needed (or --dummy-load for a resistor)")
        laser = machine.laser(args.laser)
        if args.real and not laser.pd_response_a_w and not args.datasheet_response:
            parser.error(
                f"laser {args.laser} has no power-meter response in machine.toml: "
                f"measure it in the Power tab first, or pass --datasheet-response"
            )
    if not 0 < args.max_mw <= MAX_MW:
        parser.error(f"--max-mw must be above 0 and at most {MAX_MW}")
    if not 0 < args.max_ma * 1e-3 <= MAX_I_A:
        parser.error(f"--max-ma must be above 0 and at most {MAX_I_A * 1e3:.0f}")
    if not 0 < args.i_known < MAX_I_A:
        parser.error("--i-known must be above 0 and below the current ceiling")
    if not 0 < args.i_step <= 2e-3:
        parser.error("--i-step must be above 0 and at most 2 mA")
    if args.v_known is not None and not 0 < args.v_known <= MAX_V:
        parser.error(f"--v-known must be above 0 and at most {MAX_V} V")
    unknown = set(args.stages) - set(STAGES)
    if unknown:
        parser.error(f"unknown stages: {', '.join(sorted(unknown))}")


def _confirm(args, light_a, source) -> None:
    say(
        f"Laser {args.laser} straight on channel 1 (its + on channel 1's +), "
        f"photodiode on channel 2.\n"
        f"Current forced up to the first of: {args.max_mw:g} mW of light "
        f"(stops at {light_a * 1e6:.0f} uA on the photodiode, response from the "
        f"{source}), the curve bending, {MAX_V} V, {args.max_ma:g} mA.\n"
        f"No light by {LIGHT_BY * args.i_known * 1e3:.1f} mA "
        f"({LIGHT_BY:g} x --i-known) stops it: the beam is off the photodiode.\n"
        f"The laser lights: goggles on, beam on the photodiode."
    )
    if input("Type yes to go on: ").strip().lower() != "yes":
        raise SystemExit("not started")


def polarity_check(args, clock) -> int:
    """+1.00 V on channel 1, 1 mA limit, until Enter: which terminal is +."""
    smu = _open(args, clock)
    rig = ModuleRig(smu, clock, 1, 0.1)
    try:
        rig.laser.reset()
        rig.force_voltage(POLARITY_LIMIT_A)
        rig.set(POLARITY_V)
        clock.sleep(0.2)
        v, i, _ = rig.read(1)
        say(
            f"Channel 1 is at {v:+.3f} V ({i * 1e6:.1f} uA) with a 1 mA limit.\n"
            f"Nothing should be connected. The terminal where the multimeter's "
            f"red probe reads +{POLARITY_V:.2f} V is where the module's + goes."
        )
        if not args.sim:
            input("Press Enter to switch it off.")
    finally:
        rig.off()
        smu.close()
    say("Channel 1 off.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = base_parser(__doc__.strip().split("\n")[0])
    parser.add_argument("--port", default="", help="miniSMU port (default: machine.toml)")
    parser.add_argument("--polarity-check", action="store_true",
                        help="+1 V on channel 1 with nothing connected, then stop")
    parser.add_argument("--dummy-load", action="store_true",
                        help="a 100 ohm resistor on channel 1, to watch the limits "
                             "hold before any laser: no light checks")
    parser.add_argument("--laser", type=int, choices=range(1, 7), help="which laser this is")
    parser.add_argument("--i-known", type=parse_amps,
                        help="current it draws on the laser board today, e.g. 32m "
                             "(only to check the beam is seen)")
    parser.add_argument("--v-known", type=float,
                        help="volts across it on the laser board today (for the verdict)")
    parser.add_argument("--max-mw", type=float, default=MAX_MW,
                        help=f"light ceiling, mW (at most {MAX_MW})")
    parser.add_argument("--max-ma", type=float, default=MAX_I_A * 1e3,
                        help=f"current ceiling, mA (at most {MAX_I_A * 1e3:.0f})")
    parser.add_argument("--datasheet-response", action="store_true",
                        help="no power-meter response: use the datasheet curve, "
                             "with a wider margin")
    parser.add_argument("--i-step", type=parse_amps, default=0.5e-3,
                        help="largest current step (default 0.5m)")
    parser.add_argument("--v-step", type=float, default=0.05)
    parser.add_argument("--reads", type=int, default=3, help="readings averaged a point")
    parser.add_argument("--settle-ms", type=float, default=100.0)
    parser.add_argument("--hold-s", type=float, default=60.0)
    parser.add_argument("--gap-s", type=float, default=5.0, help="dark between the holds")
    parser.add_argument("--every-s", type=float, default=0.5, help="hold reading interval")
    parser.add_argument("--stages", type=lambda s: [x.strip() for x in s.split(",")],
                        default=list(STAGES))
    parser.add_argument("--module", choices=("regulated", "resistor", "starved", "rollover", "laser4", "laser3"),
                        default="regulated", help="--sim only: the simulated module")
    parser.add_argument("--yes", action="store_true", help="don't ask before lighting")
    parser.add_argument("--no-plot", action="store_true")
    args = parser.parse_args(argv)

    machine, clock = setup(args)
    _check_args(parser, args, machine)
    if args.real and not args.port:
        args.port = machine.ports().smu
        if not args.port:
            parser.error("pass --port (no smu port in machine.toml here)")
    if args.polarity_check:
        return polarity_check(args, clock)

    light_a, response, source = light_ceiling(args, machine)
    caps = Caps(args.max_ma * 1e-3, light_a)
    report = Report("laser_module", args)
    results = report.data["results"]
    report["dummy_load"] = args.dummy_load
    if args.laser:
        report["laser"] = {
            "number": args.laser,
            "wavelength_nm": machine.laser(args.laser).wavelength_nm,
        }
    report["ceilings"] = {
        "light_mw": args.max_mw,
        "light_pd_a": light_a,
        "pd_response_a_w": response,
        "response_from": source,
        "voltage_v": MAX_V,
        "current_a": caps.i_a,
        "light_by_a": LIGHT_BY * args.i_known,
    }
    if args.real and not args.yes and not args.dummy_load:
        _confirm(args, light_a, source)

    smu = _open(args, clock)
    rig = ModuleRig(smu, clock, args.reads, args.settle_ms / 1000.0)
    try:
        report["identity"] = smu.identify()
        rig.start()
        stage_dark(rig, report)
        if "current" in args.stages:
            current = stage_current(rig, report, args, caps)
            report["judged_current"] = judge_current(
                current["up"], current["down"], rig.dark, response
            )
            i_op, v_op, i_max = operating_point(current["up"], rig.dark, rig.lit_a)
            report["operating_point"] = {"a": i_op, "v": v_op, "i_max_a": i_max}
            voltage = None
            if "voltage" in args.stages or "hold" in args.stages:
                prove_current_limit(rig, report, report["judged_current"],
                                    current["up"], caps)
            if "voltage" in args.stages:
                voltage = stage_voltage(rig, report, args, caps, v_op, i_max,
                                        report["judged_current"])
                if voltage["to_v"] >= MAX_V:
                    report["judged_voltage"] = judge_voltage(
                        voltage["points"], rig.dark, response,
                        QUOTE_V + ((args.v_known,) if args.v_known else ()),
                    )
            if "hold" in args.stages:
                held = stage_hold(rig, report, args, caps, i_op, v_op, i_max, voltage)
                report["judged_hold"] = {
                    key: judge_hold(held[key]["points"], rig.dark)
                    for key in ("constant_voltage", "constant_current")
                }
    except StopRun as stop:
        report["stopped"] = str(stop)
        say(f"STOPPED: {stop}")
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        say(f"FAILED: {report['error']}")
        raise
    finally:
        try:
            rig.off()
            smu.output_off()
        except Exception as exc:
            report.note(f"output off failed: {exc}")
        lines = verdict(results, args)
        report["verdict"] = lines
        if lines:
            say("\nWhat it says:")
            for line in lines:
                say(f"- {line}")
        path = report.save()
        smu.close()
        if not args.no_plot:
            _plot(results, path.with_suffix(".png"))
    return 0


def _plot(results: dict, path) -> None:
    """V against I, light against current, and light over the holds."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    dark = results.get("dark", {}).get("pd_a", {}).get("mean", 0.0)
    current = results.get("current", {})
    fig, axes = plt.subplots(1, 4, figsize=(20, 4.5))
    ax = axes[0]
    for key, style in (("up", "o-"), ("down", "x--")):
        pts = current.get(key, [])
        if pts:
            ax.plot([p["i"] * 1e3 for p in pts], [p["v"] for p in pts], style,
                    ms=3, label=f"current {key}")
    pts = results.get("voltage", {}).get("points", [])
    if pts:
        ax.plot([p["i"] * 1e3 for p in pts], [p["v"] for p in pts], "s",
                ms=3, label="voltage forced")
    ax.set(xlabel="mA", ylabel="V", title="Voltage the module needs")
    ax.legend()
    ax = axes[1]
    for key, style in (("up", "o-"), ("down", "x--")):
        pts = current.get(key, [])
        if pts:
            ax.plot([p["i"] * 1e3 for p in pts],
                    [abs(p["pd"] - dark) * 1e6 for p in pts], style, ms=3, label=key)
    cap = results.get("ceilings", {}).get("light_pd_a")
    if cap:
        ax.axhline(cap * 1e6, color="grey", ls=":", label="light ceiling")
    ax.set(xlabel="mA", ylabel="photodiode, uA", title="Light against current")
    ax.legend()
    ax = axes[2]
    pts = results.get("voltage", {}).get("points", [])
    if pts:
        ax.plot([p["v"] for p in pts], [abs(p["pd"] - dark) * 1e6 for p in pts],
                "o-", ms=3, label="light")
        ax.set(xlabel="V forced", ylabel="photodiode, uA", title="On a plain supply")
        twin = ax.twinx()
        twin.plot([p["v"] for p in pts], [p["i"] * 1e3 for p in pts], "s:",
                  ms=2, color="grey", label="current")
        twin.set_ylabel("mA")
        ax.legend(loc="upper left")
    ax = axes[3]
    for key in ("constant_voltage", "constant_current"):
        pts = results.get("hold", {}).get(key, {}).get("points", [])
        light = [abs(p["pd"] - dark) for p in pts]
        if light and light[0]:
            ax.plot([p["t"] for p in pts], [(x / light[0] - 1) * 100 for x in light],
                    label=key.replace("_", " "))
    ax.set(xlabel="s", ylabel="light, % from the first reading", title="Held")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    say(f"plot: {path}")


if __name__ == "__main__":
    sys.exit(main())
