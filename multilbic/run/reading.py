"""
Reading one SMU channel with no motion: dark, then under each laser
asked for (Phase 6 step 8, `multilbic read`).

For the photodiode on channel 2 before anything is built around it: the
dark reading shows the wiring and the noise floor, and a reading under
each laser shows the sign, the size and the range `commission` will
need. The stage is not homed and does not move: the photodiode is put
under the laser beforehand (jog it there in the window, then close the
window, which holds the machine lock), unless each laser is given a
place: then the stage homes and goes to each laser's place in turn.

Single readings, on autorange as the range check takes them
(`run/ranges.py`), or on a fixed range. Autorange can return a wild
reading as it switches: laser 3 at about -0.5 mA, near the top of the
650 uA range, gave one reading of +6.2 mA among fifty (bench,
2026-10-29). So a reading is summarised by its median and the median
absolute deviation, readings far from the median are counted as
outliers and left out of the mean, and every value is kept in the file.
"""

from __future__ import annotations

import math
import statistics
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from multilbic.clock import Clock
from multilbic.config.machine import MachineConfig
from multilbic.run.motion import RunStopped, approach
from multilbic.run.ranges import AT_LIMIT_SHARE, choose_range
from multilbic.run.rows import ScanDevices, current_limit_for

#: How long each reading averages, s.
READ_S = 2.0
#: How long a laser is on before it is read, s: past the first flicker,
#: not a warm-up (laser 2 doubles over two minutes, D16).
LIGHT_SETTLE_S = 2.0
#: Fewer readings than this make no mean worth printing.
MIN_READINGS = 3
#: A reading further than this many robust standard deviations from the
#: median, plus `OUTLIER_SHARE` of the median, is an outlier.
OUTLIER_SIGMAS = 8.0
OUTLIER_SHARE = 0.05
#: Nothing within 1 nA of the median is an outlier: a quiet, quantised
#: dark reading can have a median absolute deviation of 0.
OUTLIER_FLOOR_A = 1e-9
#: MAD to standard deviation, for normal noise.
MAD_TO_SD = 1.4826


class ReadStopped(RunStopped):
    pass


def amps(value: float) -> str:
    """'12.34 nA', '-1.203 uA'."""
    if not math.isfinite(value):
        return "-"
    for unit, scale in (("mA", 1e-3), ("uA", 1e-6), ("nA", 1e-9)):
        if abs(value) >= scale:
            return f"{value / scale:.4g} {unit}"
    return f"{value / 1e-12:.3g} pA"


@dataclass(frozen=True)
class Reading:
    #: 0 for dark.
    laser: int
    values: tuple[float, ...]
    median_a: float
    #: The robust standard deviation: 1.4826 x the median absolute
    #: deviation.
    scatter_a: float
    #: The mean of the readings that are not outliers.
    mean_a: float
    min_a: float
    max_a: float
    outliers: int
    #: A reading (not an outlier) reached the current limit: the truth
    #: may be larger.
    at_limit: bool
    limit_a: float
    #: The voltage the SMU measured with each reading: whether it held
    #: the bias.
    volts: tuple[float, ...] = ()

    @property
    def n(self) -> int:
        return len(self.values)

    @property
    def peak_a(self) -> float:
        """The largest magnitude among the readings that aren't
        outliers."""
        return max(abs(self.min_a), abs(self.max_a))

    @property
    def median_v(self) -> float | None:
        return statistics.median(self.volts) if self.volts else None

    def held(self) -> str:
        v = self.median_v
        return "" if v is None else f", at {v:+.4f} V"

    def as_dict(self) -> dict[str, Any]:
        return {"median_a": self.median_a, "scatter_a": self.scatter_a,
                "mean_a": self.mean_a, "min_a": self.min_a,
                "max_a": self.max_a, "n": self.n, "outliers": self.outliers,
                "at_limit": self.at_limit, "limit_a": self.limit_a,
                "median_v": self.median_v, "values_a": list(self.values),
                "values_v": list(self.volts)}


def summarise(laser: int, values: Sequence[float],
              limit_a: float = current_limit_for(None),
              volts: Sequence[float] = ()) -> Reading:
    if not values:
        raise ValueError("no readings")
    median = statistics.median(values)
    mad = statistics.median(abs(v - median) for v in values)
    scatter = MAD_TO_SD * mad
    reach = max(OUTLIER_SIGMAS * scatter + OUTLIER_SHARE * abs(median),
                OUTLIER_FLOOR_A)
    kept = [v for v in values if abs(v - median) <= reach] or [median]
    return Reading(
        laser, tuple(values), median, scatter, statistics.fmean(kept),
        min(kept), max(kept), len(values) - len(kept),
        max(abs(v) for v in kept) >= AT_LIMIT_SHARE * limit_a, limit_a,
        tuple(volts),
    )


#: Where a laser is read: X, Y, A, B in mm.
Place = tuple[float, float, float, float]


@dataclass
class ChannelReading:
    channel: int
    bias_v: float
    #: Every laser off, before the first laser, on `current_range_a`.
    dark: Reading
    lit: dict[int, Reading] = field(default_factory=dict)
    #: The range everything not named in `ranges` is read on; None for
    #: autorange.
    current_range_a: float | None = None
    #: Each laser's own range, where it differs.
    ranges: dict[int, float | None] = field(default_factory=dict)
    #: Each laser's own dark, read on its range with every laser off,
    #: just before it: channel 2's offset depends on the range.
    darks: dict[int, Reading] = field(default_factory=dict)
    #: Where each laser was read, if the stage was moved there.
    places: dict[int, Place] = field(default_factory=dict)

    def range_of(self, laser: int) -> float | None:
        return self.ranges.get(laser, self.current_range_a)

    def dark_of(self, laser: int) -> Reading:
        return self.darks.get(laser, self.dark)

    def net_a(self, laser: int) -> float:
        """Under the laser, less dark, from the medians."""
        return self.lit[laser].median_a - self.dark_of(laser).median_a

    def range_a(self, laser: int) -> float:
        """The fixed range a run or `commission` would pick for it: the
        smallest holding 3x the largest reading."""
        return choose_range(self.lit[laser].peak_a)

    @staticmethod
    def setting(range_a: float | None) -> str:
        if range_a is None:
            return "autorange"
        return f"{amps(range_a)} range"

    def dark_line(self) -> str:
        d = self.dark
        return (f"channel {self.channel} at {self.bias_v:g} V, "
                f"{self.setting(self.current_range_a)}, dark: "
                f"{_summary(d)}")

    def laser_lines(self, n: int) -> list[str]:
        r, d = self.lit[n], self.dark_of(n)
        net = self.net_a(n)
        sign = "positive" if net > 0 else "negative"
        out = []
        if n in self.places:
            x, y, a, b = self.places[n]
            out.append(f"laser {n} at X{x:g} Y{y:g} A{a:g} B{b:g}")
        if n in self.darks:
            out.append(f"laser {n}'s dark, "
                       f"{self.setting(self.range_of(n))}: {_summary(d)}")
        out.append(f"laser {n}: {amps(r.median_a)}, {amps(net)} above dark "
                   f"({sign}), scatter {amps(r.scatter_a)}, from "
                   f"{amps(r.min_a)} to {amps(r.max_a)}{r.held()}; range "
                   f"{amps(self.range_a(n))}")
        if r.outliers:
            out.append(f"  {r.outliers} of {r.n} readings far off and left "
                       "out (autorange switching?)")
        if r.at_limit:
            out.append(f"  reaches the {amps(r.limit_a)} current limit: "
                       "maybe brighter; read on a larger fixed range")
        if abs(net) < 10 * max(d.scatter_a, r.scatter_a, 1e-12):
            out.append(f"  laser {n} hardly shows: is the photodiode "
                       "under it, and its lead on this channel?")
        return out

    def lines(self) -> list[str]:
        out = [self.dark_line()]
        for n in sorted(self.lit):
            out.extend(self.laser_lines(n))
        return out

    def as_dict(self) -> dict[str, Any]:
        lasers: dict[str, Any] = {}
        for n, r in sorted(self.lit.items()):
            entry = {**r.as_dict(), "net_a": self.net_a(n),
                     "range_a": self.range_a(n),
                     "read_on_range_a": self.range_of(n)}
            if n in self.darks:
                entry["dark"] = self.darks[n].as_dict()
            if n in self.places:
                entry["xyab_mm"] = list(self.places[n])
            lasers[str(n)] = entry
        return {"channel": self.channel, "bias_v": self.bias_v,
                "current_range_a": self.current_range_a,
                "dark": self.dark.as_dict(), "lasers": lasers}


def _summary(d: Reading) -> str:
    return (f"{amps(d.median_a)} (scatter {amps(d.scatter_a)}, {d.n} "
            "readings" + (f", {d.outliers} outliers" if d.outliers else "")
            + d.held() + ")")


def read_channel(
    devices: ScanDevices,
    machine: MachineConfig,
    clock: Clock,
    *,
    channel: int = 2,
    lasers: Sequence[int] = (),
    read_s: float = READ_S,
    settle_s: float = LIGHT_SETTLE_S,
    bias_v: float = 0.0,
    current_range_a: float | None = None,
    ranges: Mapping[int, float | None] | None = None,
    places: Mapping[int, Place] | None = None,
    stop: threading.Event | None = None,
    say: Callable[[str], None] = print,
) -> ChannelReading:
    """Dark first, every laser off, then each of `lasers` in turn, on
    autorange or a fixed range (its current limit its full scale, as
    runs set it): `current_range_a`, or the laser's own in `ranges`. A
    laser on a range of its own gets its own dark on that range, read
    just before it.

    With `places`, the stage homes first and goes to each laser's place
    (X, Y, A, B) before it comes on; a laser without one is read
    wherever the stage is. Without, nothing moves.

    Ends with every laser and the channel off, however it ends, and any
    motion stopped. `stop` set raises `ReadStopped` between steps."""
    per_laser = dict(ranges or {})
    where = dict(places or {})
    for n in lasers:
        machine.laser(n)  # KeyError before anything is switched on
    smu, board, marlin = devices.smu, devices.laser, devices.marlin
    if channel not in smu.channels:
        raise ValueError(f"the SMU was opened for channels {smu.channels}, "
                         f"not {channel}")
    halt = stop or threading.Event()

    def check_stop() -> None:
        if halt.is_set():
            raise ReadStopped("stopped")

    def set_range(range_a: float | None) -> None:
        smu.prepare(bias_v=bias_v, current_limit_a=current_limit_for(range_a),
                    current_range_a=range_a)
        smu.output_on()

    def read(laser: int, range_a: float | None) -> Reading:
        values: list[float] = []
        volts: list[float] = []
        until = clock.now() + read_s
        while clock.now() < until or len(values) < MIN_READINGS:
            check_stop()
            v, i = smu.measure(channel)
            volts.append(v)
            values.append(i)
        return summarise(laser, values, current_limit_for(range_a), volts)

    board.off()
    moving = False
    try:
        if where:
            say("homing")
            moving = True
            marlin.home()
        set_range(current_range_a)
        say(f"every laser off: reading channel {channel} dark for "
            f"{read_s:g} s")
        result = ChannelReading(channel, bias_v, read(0, current_range_a),
                                current_range_a=current_range_a)
        say(result.dark_line())
        on_range = current_range_a
        for n in lasers:
            check_stop()
            if n in where:
                x, y, a, b = where[n]
                say(f"to laser {n}'s place: X{x:g} Y{y:g} A{a:g} B{b:g}")
                approach(marlin, machine, x=x, y=y, a=a, b=b, stop=halt)
                result.places[n] = (x, y, a, b)
            range_a = per_laser.get(n, current_range_a)
            if n in per_laser:
                result.ranges[n] = range_a
            if range_a != on_range:
                set_range(range_a)
                on_range = range_a
            if n in per_laser and range_a != current_range_a:
                result.darks[n] = read(0, range_a)
            say(f"laser {n} on")
            board.select(n)
            clock.sleep(settle_s)
            result.lit[n] = read(n, range_a)
            board.off()
            for line in result.laser_lines(n):
                say(line)
        return result
    except BaseException:
        if moving:
            try:
                marlin.quickstop()
            except Exception as exc:
                say(f"stopping the stage failed: {exc}")
        raise
    finally:
        for off in (board.off, smu.output_off):
            try:
                off()
            except Exception as exc:
                say(f"switching off failed: {exc}")
