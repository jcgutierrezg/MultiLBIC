"""
Where a laser landed this time: placing each map from the photodiode.

The revolver's servo lands a laser within about +-0.1 mm, differently
every time it turns (bench, 2026-11-04: 44 um spread along A, 20 um
along B, after each return; 0.1 um with the servo still). So a laser's
`xy_centre_mm` from commissioning is where it landed then, not where it
is now. A run that locates each laser right after selecting it, before
its map, places that map from where the laser really is: the servo
doesn't move again until the next laser.

**Quick.** The laser is lit on the photodiode's open quarter as
commissioning does (`Commissioner._find`: the dark, the selection, the
range). Each blade edge is then swept +-`QUICK_HALF_MM` round where it
would be with the laser at its `xy_centre_mm`, fitted from the brightest
point towards the blade, and crossed again once up and once down,
slowly; the mean of those two is the edge. About 30-40 s a laser. If a
sweep misses (the laser further off than the servo moves it), the full
commissioning sweeps take over.

**Broader, once.** If those fail too, a run tries once more with the
sweeps widened (`locate(broad=True)`): laser 2, dim and drifting, failed
twice on 2026-11-06 with its edge along B outside the quick sweep. If
that fails, the run asks what to do (`Session`).

**The answer** is the corner as the laser sees it, against the measured
corner: the laser is that much off its `xy_centre_mm`, and its map's XY
moves by as much (`propose`'s arithmetic, for this run only).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from multilbic.run.commission import (
    AXES,
    COARSE_HALF_MM,
    FINE_HALF_MIN_MM,
    FINE_WIDTHS,
    FIRST_RANGE_A,
    Commissioner,
    CommissionError,
    CommissionRequest,
    LaserCommission,
)
from multilbic.run.motion import approach, check
from multilbic.run.reading import Reading, amps
from multilbic.scan.geometry import ab_to_xy

#: The quick sweep spans this either side of where an edge should be:
#: more than the servo's landing scatter.
QUICK_HALF_MM = 0.4
QUICK_FEED_MM_S = 0.15
#: The second, broader try: the quick sweeps and the coarse ones span
#: this either side instead.
BROAD_QUICK_HALF_MM = 0.8
BROAD_COARSE_HALF_MM = 3.0
#: The up and down passes across each edge.
CHECK_FEED_MM_S = 0.1
#: Dark and light readings, s: short, the range is all they decide.
READ_S = 0.5
#: Roughly how long a laser's locate takes, for estimates.
LOCATE_S = 40.0
#: The power read on the open quarter before and after each map, s.
POWER_READ_S = 5.0
#: A reading every this often through the warm-up, kept in the file.
WARMUP_TICK_S = 1.0
#: Roughly what the power readings add to a laser, for estimates: the
#: trips between sample and photodiode, the reading after and the dark.
POWER_S = 20.0


@dataclass(frozen=True)
class LaserFix:
    laser: int
    #: The blades' corner as the laser saw it, carriage frame, mm.
    corner_mm: tuple[float, float]
    #: How far the laser is off its `xy_centre_mm`: added to its map's XY.
    offset_xy_mm: tuple[float, float]
    #: Each edge's 10-90 % width (along A, along B), mm.
    widths_mm: tuple[float, float]
    #: Up minus down on each edge, mm.
    splits_mm: tuple[float, float]
    #: The light on the open quarter, A (the step at the edges).
    light_a: float
    #: The quick sweeps found it; False: the full sweeps were needed.
    quick: bool
    seconds: float
    #: The photodiode's range it was read on: the power is read on it too.
    range_a: float | None = None

    def line(self) -> str:
        dx, dy = self.offset_xy_mm
        return (f"laser {self.laser} located: {dx * 1000:+.0f}, "
                f"{dy * 1000:+.0f} um off machine.toml, spot "
                f"{self.widths_mm[0] * 1000:.0f} um"
                + ("" if self.quick else " (full sweeps)")
                + f", {self.seconds:.0f} s")

    def as_dict(self) -> dict[str, Any]:
        return {"laser": self.laser, "corner_mm": list(self.corner_mm),
                "offset_xy_mm": list(self.offset_xy_mm),
                "widths_mm": list(self.widths_mm),
                "splits_mm": list(self.splits_mm), "light_a": self.light_a,
                "quick": self.quick, "seconds": round(self.seconds, 1),
                "range_a": self.range_a}


class Locator(Commissioner):
    """Locates one laser at a time; the laser is left lit (selected), so
    the map that follows uses this landing."""

    quick_half_mm = QUICK_HALF_MM

    def locate(self, laser: int, *, broad: bool = False) -> LaserFix:
        """Where `laser` landed. `broad`: the sweeps widened, for a
        second try. Raises `CommissionError` if it isn't found."""
        if not broad:
            return self._locate(laser)
        self.quick_half_mm = BROAD_QUICK_HALF_MM
        self.coarse_half_mm = BROAD_COARSE_HALF_MM
        try:
            return self._locate(laser)
        finally:
            self.quick_half_mm = QUICK_HALF_MM
            self.coarse_half_mm = COARSE_HALF_MM

    def _locate(self, laser: int) -> LaserFix:
        pd = self.pd
        request = CommissionRequest((laser,), warmup_s=0.0, read_s=READ_S)
        r = LaserCommission(laser)
        t0 = self.clock.now()
        self._range = None  # a map since may have set the SMU otherwise
        self.devices.laser.off()
        light = self._find(r, request)
        try:
            light, corner, widths, splits = self._quick(r, request, light)
            quick = True
        except CommissionError as exc:
            self.say(f"laser {laser}: the quick locate missed ({exc}); "
                     "the full sweeps")
            assert r.found_mm is not None
            light = self._coarse(r, request, r.found_mm, light, (0, 1))
            self._fine(r, request, light)
            assert r.corner_mm is not None
            corner = r.corner_mm
            widths = (r.edges[0].width_mm, r.edges[1].width_mm)
            splits = (r.edges[0].split_mm, r.edges[1].split_mm)
            quick = False
        g = self.machine.geometry
        dx, dy = ab_to_xy(g.x_along, g.y_along,
                          corner[0] - pd.corner_ab_mm[0],
                          corner[1] - pd.corner_ab_mm[1])
        fix = LaserFix(laser, corner, (dx, dy), widths, splits, light,
                       quick, self.clock.now() - t0, r.range_a)
        self.say(fix.line())
        return fix

    def _quick(
        self, r: LaserCommission, request: CommissionRequest, light: float,
    ) -> tuple[float, tuple[float, float], tuple[float, float],
               tuple[float, float]]:
        """Each edge from a short sweep round where it should be, then up
        and down across it. Raises `CommissionError` if a sweep finds no
        edge."""
        n = r.laser
        signs = self.pd.open_signs
        quarter = self.pd.chip_mm / 4
        expected = self.pd.corner_ab_mm
        edge = list(expected)
        widths, splits = [0.0, 0.0], [0.0, 0.0]
        for k in (0, 1):
            other = edge[1 - k] + signs[1 - k] * quarter
            start = self._clip(n, k,
                               expected[k] + signs[k] * self.quick_half_mm)
            end = self._clip(n, k,
                             expected[k] - signs[k] * self.quick_half_mm)
            sweep = self._ranged_pass(r, k, start, end, other,
                                      QUICK_FEED_MM_S, light * signs[k],
                                      blade_side=-signs[k])
            if sweep.fit is None:
                raise CommissionError(
                    f"no edge along {AXES[1 - k]} within "
                    f"{self.quick_half_mm:g} mm of where it should be "
                    f"({sweep.error})")
            seen = sweep.fit.step_a * signs[k]
            if abs(seen) > abs(light):
                light = seen
            half = max(FINE_HALF_MIN_MM / 2,
                       FINE_WIDTHS * sweep.fit.width_mm)
            at = sweep.fit.position_mm
            lo, hi = self._clip(n, k, at - half), self._clip(n, k, at + half)
            up = self._ranged_pass(r, k, lo, hi, other, CHECK_FEED_MM_S,
                                   light * signs[k])
            down = self._ranged_pass(r, k, hi, lo, other, CHECK_FEED_MM_S,
                                     light * signs[k])
            if up.fit is None or down.fit is None:
                raise CommissionError(
                    f"the passes across the edge along {AXES[1 - k]} found "
                    f"no edge ({up.error or down.error})")
            edge[k] = (up.fit.position_mm + down.fit.position_mm) / 2
            widths[k] = (up.fit.width_mm + down.fit.width_mm) / 2
            splits[k] = up.fit.position_mm - down.fit.position_mm
        return (light, (edge[0], edge[1]), (widths[0], widths[1]),
                (splits[0], splits[1]))

    # ---- the power before and after a map (D31) ----

    def _quarter_middle(self, fix: LaserFix) -> tuple[float, float]:
        """The open quarter's middle as this landing sees it."""
        signs = self.pd.open_signs
        quarter = self.pd.chip_mm / 4
        return (fix.corner_mm[0] + signs[0] * quarter,
                fix.corner_mm[1] + signs[1] * quarter)

    def _on_quarter(self, fix: LaserFix) -> None:
        """The stage to the open quarter, the photodiode on its range."""
        self._go(fix.laser, self._quarter_middle(fix))
        # A map since has set the SMU otherwise.
        self._range = None
        self._set_range(fix.range_a if fix.range_a is not None
                        else FIRST_RANGE_A)

    def _timed_read(self, laser: int, when: str,
                    seconds: float) -> PowerReading:
        t0 = self.clock.now()
        reading = self._read(laser, seconds)
        t1 = self.clock.now()
        assert self._range is not None
        return PowerReading(laser, when, (t0 + t1) / 2, reading, self._range)

    def warm_up(self, fix: LaserFix, warmup_s: float,
                read_s: float = POWER_READ_S) -> PowerReading:
        """The laser lit on the open quarter for `warmup_s`, read every
        `WARMUP_TICK_S` (the warm-up curve), then for `read_s`: its power
        before the map. The laser is left lit."""
        n = fix.laser
        self._on_quarter(fix)
        self.devices.laser.select(n)
        lit = self.clock.now()
        curve: list[tuple[float, float]] = []
        while self.clock.now() - lit < warmup_s:
            check(self.halt)
            t, _, i = self._measure()
            curve.append((round(t - lit, 3), i))
            next_tick = lit + len(curve) * WARMUP_TICK_S
            pause = min(next_tick, lit + warmup_s) - self.clock.now()
            if pause > 0:
                self.clock.sleep(pause)
        check(self.halt)
        before = self._timed_read(n, "before", read_s)
        return PowerReading(n, "before", before.t_s, before.reading,
                            before.range_a, tuple(curve))

    def power_after(self, fix: LaserFix,
                    read_s: float = POWER_READ_S
                    ) -> tuple[PowerReading, PowerReading]:
        """The power after the map, on the open quarter, then the
        photodiode's dark on the same range, the laser off."""
        n = fix.laser
        self._on_quarter(fix)
        lit = self._timed_read(n, "after", read_s)
        self.devices.laser.off()
        dark = self._timed_read(0, "dark", read_s)
        return lit, dark


@dataclass(frozen=True)
class PowerReading:
    """The photodiode lit by one laser (or dark, laser 0) over a few
    seconds, on the open quarter's middle."""

    laser: int
    #: "before", "after" or "dark".
    when: str
    #: The middle of the reading, host clock (the rows' anchors' clock).
    t_s: float
    reading: Reading
    range_a: float
    #: The warm-up before it: (seconds since lit, A), one a tick.
    curve: tuple[tuple[float, float], ...] = ()

    @property
    def current_a(self) -> float:
        return self.reading.mean_a

    def as_dict(self) -> dict[str, Any]:
        r = self.reading
        out: dict[str, Any] = {
            "current_a": r.mean_a, "median_a": r.median_a,
            "scatter_a": r.scatter_a, "readings": r.n,
            "at_limit": r.at_limit, "range_a": self.range_a,
            "t_s": round(self.t_s, 3),
        }
        if self.curve:
            out["warmup"] = [[t, i] for t, i in self.curve]
        return out


@dataclass
class PhotodiodeStops:
    """What a run does on the photodiode around one laser's map (D31):
    `scan_laser` calls these between its baseline, its rows and its
    end."""

    locator: Locator
    fix: LaserFix
    #: Where the stage puts the sample under this landing of the laser.
    sample_xy: tuple[float, float]
    read_s: float = POWER_READ_S

    def before(self, warmup_s: float) -> dict[str, Any]:
        reading = self.locator.warm_up(self.fix, warmup_s, self.read_s)
        self.locator.say(
            f"laser {self.fix.laser}: power before "
            f"{amps(reading.current_a)} on the photodiode")
        return reading.as_dict()

    def to_sample(self) -> None:
        x, y = self.sample_xy
        loc = self.locator
        approach(loc.devices.marlin, loc.machine, x=x, y=y, stop=loc.halt)

    def after(self) -> dict[str, dict[str, Any]]:
        lit, dark = self.locator.power_after(self.fix, self.read_s)
        self.locator.say(
            f"laser {self.fix.laser}: power after {amps(lit.current_a)}, "
            f"dark {amps(dark.current_a)}")
        return {"power_after": lit.as_dict(), "power_dark": dark.as_dict()}
