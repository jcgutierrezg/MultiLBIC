"""
Commissioning with the photodiode (Phase 6 step 5, `multilbic commission`).

For each laser: bring the photodiode's open quarter under it, read its
power, then find the two blade edges with the beam. Where the edges
cross is the corner as that laser sees it; the same corner seen by two
lasers tells how far apart the lasers really are, which is what
`xy_centre_mm` should say. The edges' 10-90 % widths are the spot's
size. It ends with the changes it proposes to `machine.toml`, and
writes them only when told to (D23).

**Finding the beam.** XY and AB put the middle of the open quarter
where `machine.toml` says the laser is (`scan.photodiode.reach`). If
the channel shows no light there, the stage searches outwards on a
grid finer than the open quarter, a few mm for a measured laser and
further for one whose position is a placeholder (4-6).

**Power and range.** First read on the 15 mA range, which holds every
laser seen so far (laser 3 is 1.24 mA); then the range for the rest is
the smallest holding 3x the reading (`ranges.choose_range`), and the
power is read again on it at the end, after the warm-up and the edges,
with the dark on the same range (the channel-2 offset of 2026-10-29
was 1.7 % of the range: only a dark on the same range removes it). The
voltage the channel holds is checked against the bias; a channel
reporting more than 10 mV off is in that state, and is reported.

**Edges.** A pass moves one axis at a constant, slow feed through an
edge while the channel is read as fast as it answers. Each reading's
position comes from the time: the pass's `M400` reply marks when the
move ended, at the far end, and the stage moved at the feed before
that. A coarse pass from the open quarter's middle towards the blade
finds each edge roughly; then a slow pass up and one down across it.
The two directions see the edge shifted opposite ways by the backlash
and by any lag between reading and stamp, so their mean is the edge,
and their difference is reported (`split_mm`). At 0.05 mm/s an 18.6 ms
lag is under a micrometre. The edge along A is crossed by passes
along B and is 0.4 mm above focus; the one along B, crossed by passes
along A as rows are, is at the sample's height, and its width is the
`spot_um` proposed.

Positions are on the carriage, in calibration's frame (`scan.photodiode`).
"""

from __future__ import annotations

import datetime
import json
import math
import re
import threading
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from multilbic.clock import Clock
from multilbic.config.machine import MachineConfig, Photodiode, parse
from multilbic.hardware.marlin import Reply
from multilbic.run.motion import RunStopped, approach, check
from multilbic.run.ranges import AT_LIMIT_SHARE, choose_range
from multilbic.run.reading import Reading, amps, summarise
from multilbic.run.rows import ScanDevices, current_limit_for, next_range
from multilbic.scan.edges import EdgeFit, NoEdge, fit_edge
from multilbic.scan.geometry import ab_to_xy
from multilbic.scan.photodiode import (
    OutOfReach,
    open_quarter_middle,
    reach,
    span,
)

#: Holds every laser read so far, with room: where finding and the
#: first power reading are done.
FIRST_RANGE_A = 15e-3
#: How long a power or dark reading averages, s.
READ_S = 2.0
#: With the laser on before its power is trusted (D16: laser 2 doubles
#: in two minutes, laser 1 drifted 93 to 80 uA in half a minute).
WARMUP_S = 60.0
#: Each edge is swept three times, each finer than the last: coarse,
#: medium, then fine passes up and down. Feeds, mm/s.
COARSE_FEED_MM_S = 0.5
MEDIUM_FEED_MM_S = 0.15
FINE_FEED_MM_S = 0.05
#: The coarse sweep spans this either side of where the light was found
#: (the builder's suggestion, 2026-10-30): it sees the full light and
#: the blade whichever way the laser is off its position (laser 4 was
#: found on the edge itself, 0.9 mm off along B). Only the stretch from
#: the brightest point towards the blade is fitted, so the can window's
#: far edge, if the sweep crosses it, is left out.
COARSE_HALF_MM = 2.0
#: The medium sweep spans this either side of the coarse edge.
MEDIUM_HALF_MM = 0.6
#: A fine pass reaches this many coarse widths either side of the edge,
#: and at least `FINE_HALF_MIN_MM`.
FINE_WIDTHS = 4.0
FINE_HALF_MIN_MM = 0.3
#: The search grid: finer than the open quarter (1.8 mm), so the beam
#: lands fully on the chip at some point if it is in reach.
SEARCH_STEP_MM = 1.0
SEARCH_RADIUS_MM = 3.0
SEARCH_RADIUS_UNMEASURED_MM = 8.0
SEARCH_READINGS = 3
#: Light is there when the reading stands this many dark scatters, and
#: at least `LIT_FLOOR_A`, away from the dark.
LIT_SIGMAS = 20.0
LIT_FLOOR_A = 0.2e-6
#: An edge's step must be within this share of the light's.
EDGE_STEP_SHARE = 0.5
#: Readings averaged to find a pass's brightest point.
SMOOTH_READINGS = 7
#: The simulated SMU answers at once; no faster than this.
MIN_READ_INTERVAL_S = 0.005
#: A channel at its bias reports within this; more is the state seen on
#: channel 2 on 2026-10-29.
VOLTAGE_TOLERANCE_V = 0.01

AXES = "AB"


class CommissionError(RuntimeError):
    pass


@dataclass(frozen=True)
class EdgePass:
    #: 0 for a pass along A, 1 along B.
    axis: int
    #: +1 moving up, -1 down.
    direction: int
    feed_mm_s: float
    #: Carriage positions and currents of the readings during the move.
    positions_mm: tuple[float, ...]
    currents_a: tuple[float, ...]
    fit: EdgeFit | None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "axis": AXES[self.axis], "direction": self.direction,
            "feed_mm_s": self.feed_mm_s,
            "fit": None if self.fit is None else self.fit.as_dict(),
            "error": self.error,
            "positions_mm": list(self.positions_mm),
            "currents_a": list(self.currents_a),
        }


@dataclass(frozen=True)
class Edge:
    axis: int
    #: The mean of the passes up and down, on the carriage.
    position_mm: float
    width_mm: float
    #: Up minus down: backlash plus lag times feed.
    split_mm: float
    passes: tuple[EdgePass, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"axis": AXES[self.axis], "position_mm": self.position_mm,
                "width_mm": self.width_mm, "split_mm": self.split_mm,
                "passes": [p.as_dict() for p in self.passes]}


@dataclass
class LaserCommission:
    laser: int
    #: Where light was first found, on the carriage, and whether it
    #: took a search.
    found_mm: tuple[float, float] | None = None
    searched: bool = False
    first: Reading | None = None
    first_dark: Reading | None = None
    range_a: float | None = None
    lit: Reading | None = None
    dark: Reading | None = None
    coarse: dict[int, EdgePass] = field(default_factory=dict)
    medium: dict[int, EdgePass] = field(default_factory=dict)
    edges: dict[int, Edge] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def power_a(self) -> float | None:
        if self.lit is None or self.dark is None:
            return None
        return self.lit.median_a - self.dark.median_a

    @property
    def corner_mm(self) -> tuple[float, float] | None:
        if 0 not in self.edges or 1 not in self.edges:
            return None
        return self.edges[0].position_mm, self.edges[1].position_mm

    def lines(self) -> list[str]:
        out = [f"laser {self.laser}:"]
        if self.found_mm is not None:
            out.append(f"  light at A {self.found_mm[0]:.3f}, B "
                       f"{self.found_mm[1]:.3f}"
                       + (" (after a search)" if self.searched else ""))
        if self.power_a is not None and self.range_a is not None:
            out.append(f"  power {amps(self.power_a)} on the "
                       f"{amps(self.range_a)} range")
        for k, e in sorted(self.edges.items()):
            out.append(
                f"  edge along {AXES[1 - k]} (passes along {AXES[k]}): "
                f"{AXES[k]} {e.position_mm:.4f}, 10-90 % "
                f"{e.width_mm * 1000:.1f} um, up - down "
                f"{e.split_mm * 1000:+.1f} um")
        out.extend(f"  ! {w}" for w in self.warnings)
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            "found_mm": self.found_mm, "searched": self.searched,
            "first": None if self.first is None else self.first.as_dict(),
            "first_dark": (None if self.first_dark is None
                           else self.first_dark.as_dict()),
            "range_a": self.range_a, "power_a": self.power_a,
            "lit": None if self.lit is None else self.lit.as_dict(),
            "dark": None if self.dark is None else self.dark.as_dict(),
            "corner_mm": self.corner_mm,
            "coarse": {AXES[k]: p.as_dict() for k, p in self.coarse.items()},
            "medium": {AXES[k]: p.as_dict() for k, p in self.medium.items()},
            "edges": {AXES[k]: e.as_dict() for k, e in self.edges.items()},
            "warnings": self.warnings,
        }


# ---- what it proposes ----


@dataclass(frozen=True)
class Proposal:
    #: The laser whose view of the corner is taken as the truth; 0 for
    #: the corner measured before, which stays as it is.
    reference: int
    corner_ab_mm: tuple[float, float]
    xy_centre_mm: dict[int, tuple[float, float]]
    spot_um: dict[int, float]

    def lines(self, machine: MachineConfig) -> list[str]:
        pd = machine.photodiode
        assert pd is not None
        if self.reference:
            out = [f"[photodiode] corner_ab_mm {_pair(pd.corner_ab_mm)} -> "
                   f"{_pair(self.corner_ab_mm)}, measured = true (as laser "
                   f"{self.reference} sees it)"]
        else:
            out = [f"[photodiode] corner_ab_mm {_pair(pd.corner_ab_mm)} "
                   "stays (measured before)"]
        for n in sorted(self.xy_centre_mm):
            old = machine.laser(n)
            new = self.xy_centre_mm[n]
            dx, dy = new[0] - old.xy_centre_mm[0], new[1] - old.xy_centre_mm[1]
            spot = self.spot_um.get(n)
            out.append(
                f"laser {n}: xy_centre_mm {_pair(old.xy_centre_mm)} -> "
                f"{_pair(new)} ({dx * 1000:+.0f}, {dy * 1000:+.0f} um)"
                + (f", spot_um {old.spot_um} -> {spot:.1f}"
                   if spot is not None else "")
                + ", measured = true")
        return out

    def as_dict(self) -> dict[str, Any]:
        return {"reference": self.reference,
                "corner_ab_mm": self.corner_ab_mm,
                "xy_centre_mm": {str(n): v for n, v in
                                 sorted(self.xy_centre_mm.items())},
                "spot_um": {str(n): v for n, v in
                            sorted(self.spot_um.items())}}


def _pair(p: tuple[float, float]) -> str:
    return f"[{p[0]:.3f}, {p[1]:.3f}]"


def propose(machine: MachineConfig,
            results: dict[int, LaserCommission], *,
            new_corner: bool = False) -> Proposal:
    """The changes the corners and widths call for. Every laser moves by
    however far its view of the corner is from the corner's true place:
    a laser seeing the corner d further along A is d further along A
    than machine.toml says.

    The true place is the measured corner: the photodiode is fixed to
    the carriage, so a laser whose view moved (refocused, knocked) is
    the one that moved, the reference laser too. Calibrations stay
    right, since each records the reference laser's position when it
    was made. The first time, or with `new_corner` (the photodiode was
    moved), the reference laser's view becomes the corner, and its own
    position stays as it is."""
    pd = machine.photodiode
    if pd is None:
        raise CommissionError("machine.toml has no [photodiode]")
    corners = {n: r.corner_mm for n, r in results.items()
               if r.corner_mm is not None}
    reference = machine.geometry.reference_laser
    if pd.measured and not new_corner:
        truth = pd.corner_ab_mm
        reference = 0
    elif reference in corners:
        truth = corners[reference]
    else:
        why = ("a new corner is asked for" if pd.measured
               else "the corner has not been measured")
        raise CommissionError(
            f"{why}: commission laser {reference} (the reference) too")
    g = machine.geometry
    xy: dict[int, tuple[float, float]] = {}
    spot: dict[int, float] = {}
    for n, corner in corners.items():
        old = machine.laser(n).xy_centre_mm
        dx, dy = ab_to_xy(g.x_along, g.y_along,
                          corner[0] - truth[0], corner[1] - truth[1])
        xy[n] = (old[0] + dx, old[1] + dy)
        if 0 in results[n].edges:
            spot[n] = results[n].edges[0].width_mm * 1000.0
    return Proposal(reference, (float(truth[0]), float(truth[1])), xy, spot)


_NUMBER = re.compile(r"^\s*number\s*=\s*(\d+)")
_HEADER = re.compile(r"^\s*\[")


def apply_proposal(text: str, proposal: Proposal, when: str,
                   source: str = "commission") -> str:
    """machine.toml's text with the proposal written in, everything else
    (comments included) as it was. Each changed line says where it came
    from (`# <source> <when>`). A corner measured before is left alone.
    Checked by loading the result."""
    lines = text.splitlines(keepends=True)
    blocks: list[tuple[str, int, int]] = []  # (header, start, end)
    starts = [i for i, line in enumerate(lines) if _HEADER.match(line)]
    for k, i in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        blocks.append((lines[i].strip(), i, end))
    note = f"  # {source} {when}"

    def set_key(start: int, end: int, key: str, value: str,
                after: str | None = None) -> None:
        pattern = re.compile(rf"^(\s*){key}\s*=")
        for i in range(start, end):
            m = pattern.match(lines[i])
            if m:
                lines[i] = f"{m.group(1)}{key} = {value}{note}\n"
                return
        # Not there: after the `after` key, or at the block's end.
        at = end
        if after is not None:
            pa = re.compile(rf"^\s*{after}\s*=")
            for i in range(start, end):
                if pa.match(lines[i]):
                    at = i + 1
                    break
        lines.insert(at, f"{key} = {value}{note}\n")

    # Back to front, so inserting a line moves no block still to come.
    for header, start, end in reversed(blocks):
        if header == "[photodiode]" and proposal.reference:
            c = proposal.corner_ab_mm
            set_key(start, end, "measured", "true")
            set_key(start, end, "corner_ab_mm", f"[{c[0]:.3f}, {c[1]:.3f}]")
        elif header == "[[lasers]]":
            number = None
            for i in range(start, end):
                m = _NUMBER.match(lines[i])
                if m:
                    number = int(m.group(1))
                    break
            if number is None or number not in proposal.xy_centre_mm:
                continue
            x, y = proposal.xy_centre_mm[number]
            if number in proposal.spot_um:
                set_key(start, end, "spot_um",
                        f"{proposal.spot_um[number]:.1f}", after="measured")
            set_key(start, end, "measured", "true")
            set_key(start, end, "xy_centre_mm", f"[{x:.3f}, {y:.3f}]")
    out = "".join(lines)
    _check_applied(out, proposal)
    return out


def _check_applied(text: str, proposal: Proposal) -> None:
    machine = parse(tomllib.loads(text), "proposed machine.toml")
    pd = machine.photodiode
    wrong: list[str] = []
    if (pd is None or not pd.measured
            or not np.allclose(pd.corner_ab_mm, proposal.corner_ab_mm,
                               atol=6e-4)):
        wrong.append("[photodiode]")
    for n, xy in proposal.xy_centre_mm.items():
        laser = machine.laser(n)
        spot = proposal.spot_um.get(n)
        if (not laser.measured
                or not np.allclose(laser.xy_centre_mm, xy, atol=6e-4)
                or (spot is not None and (laser.spot_um is None
                                          or abs(laser.spot_um - spot) > 0.06))):
            wrong.append(f"laser {n}")
    if wrong:
        raise CommissionError(
            f"writing the proposal into machine.toml went wrong for "
            f"{', '.join(wrong)}: nothing written")


# ---- the work ----


@dataclass(frozen=True)
class CommissionRequest:
    lasers: tuple[int, ...]
    warmup_s: float = WARMUP_S
    read_s: float = READ_S
    bias_v: float = 0.0
    coarse_feed_mm_s: float = COARSE_FEED_MM_S
    fine_feed_mm_s: float = FINE_FEED_MM_S
    note: str = ""
    #: The photodiode was moved: take the reference laser's view of the
    #: corner again (`propose`).
    new_corner: bool = False


@dataclass
class CommissionResult:
    request: CommissionRequest
    lasers: dict[int, LaserCommission]
    proposal: Proposal | None
    error: str | None = None

    def lines(self, machine: MachineConfig) -> list[str]:
        out: list[str] = []
        for r in self.lasers.values():
            out.extend(r.lines())
        if self.proposal is not None:
            out.append("proposed for machine.toml:")
            out.extend("  " + line for line in self.proposal.lines(machine))
        if self.error:
            out.append(f"no proposal: {self.error}")
        return out


class Commissioner:
    """Runs the commissioning on the devices. `request_stop()` from any
    thread stops it at once: motion stops, laser and channel off."""

    def __init__(
        self,
        devices: ScanDevices,
        machine: MachineConfig,
        clock: Clock,
        *,
        say: Callable[[str], None] = print,
    ):
        pd = machine.photodiode
        if pd is None:
            raise CommissionError("machine.toml has no [photodiode]")
        if pd.channel not in devices.smu.channels:
            raise CommissionError(
                f"the SMU was opened for channels {devices.smu.channels}, "
                f"not the photodiode's {pd.channel}")
        self.devices = devices
        self.machine = machine
        self.pd: Photodiode = pd
        self.clock = clock
        self.say = say
        self.halt = threading.Event()
        self._range: float | None = None
        self._bias = 0.0

    def partial(self, error: str) -> CommissionResult | None:
        """What a run that failed had measured, with why it failed;
        None if it never started."""
        request = getattr(self, "request", None)
        if request is None:
            return None
        return CommissionResult(request, dict(self.results), None, error)

    def request_stop(self) -> None:
        self.halt.set()
        try:
            self.devices.marlin.quickstop()
        except Exception:  # noqa: S110 - stopping anyway
            pass

    def run(self, request: CommissionRequest) -> CommissionResult:
        for n in request.lasers:
            self.machine.laser(n)  # KeyError before anything moves
        d = self.devices
        self._bias = request.bias_v
        results: dict[int, LaserCommission] = {}
        #: What was measured so far, kept when the run fails, so a
        #: failed run's readings can be saved (`partial`).
        self.results = results
        self.request = request
        d.laser.off()
        try:
            self.say("homing")
            d.marlin.home()
            for n in request.lasers:
                result = LaserCommission(n)
                results[n] = result
                self._laser(result, request)
        except BaseException:
            try:
                d.marlin.quickstop()
            except Exception:  # noqa: S110 - already failing
                pass
            raise
        finally:
            for off in (d.laser.off, d.smu.output_off):
                try:
                    off()
                except Exception as exc:
                    self.say(f"switching off failed: {exc}")
        try:
            proposal: Proposal | None = propose(
                self.machine, results, new_corner=request.new_corner)
            error = None
        except CommissionError as exc:
            proposal, error = None, str(exc)
        return CommissionResult(request, results, proposal, error)

    # ---- one laser ----

    def _laser(self, r: LaserCommission, request: CommissionRequest) -> None:
        light = self._find(r, request)
        assert r.found_mm is not None
        light = self._coarse(r, request, r.found_mm, light, (0, 1))
        self._fine(r, request, light)
        self._power(r, request)

    def _find(self, r: LaserCommission, request: CommissionRequest) -> float:
        """The open quarter under laser `r.laser` (light on), its first
        reading and the range for the rest. Returns the light: the
        reading less the dark. The laser must be off to start (the dark
        is read first); it ends lit."""
        n = r.laser
        d = self.devices
        middle = open_quarter_middle(self.machine)
        self.say(f"laser {n}: to the open quarter")
        try:
            self._go(n, middle)
        except OutOfReach as exc:
            raise CommissionError(
                f"laser {n}: the open quarter is beyond its reach ({exc})"
            ) from None
        self._set_range(FIRST_RANGE_A)
        r.first_dark = self._read(0, request.read_s)
        self._check_voltage(r, r.first_dark, "dark")
        self.say(f"laser {n} on" + (f", warming up {request.warmup_s:g} s"
                                    if request.warmup_s else ""))
        d.laser.select(n)
        self._sleep(request.warmup_s)
        first = self._read(n, request.read_s)
        found = middle
        if not self._lit(first, r.first_dark):
            radius = (SEARCH_RADIUS_MM if self.machine.laser(n).measured
                      else SEARCH_RADIUS_UNMEASURED_MM)
            self.say(f"laser {n}: no light at the open quarter "
                     f"({amps(first.median_a)}); searching {radius:g} mm "
                     "around it")
            hit = self._search(n, middle, radius, r.first_dark)
            if hit is None:
                raise CommissionError(
                    f"laser {n}: no light on the photodiode within "
                    f"{radius:g} mm of where it should be")
            found, first = hit
            r.searched = True
        r.found_mm = found
        r.first = first
        net = abs(first.median_a - r.first_dark.median_a)
        r.range_a = choose_range(net)
        if first.at_limit:
            larger = next_range(FIRST_RANGE_A)
            if larger is None:
                raise CommissionError(f"laser {n} is beyond every range")
            r.range_a = larger
        self.say(f"laser {n}: {amps(first.median_a - r.first_dark.median_a)}"
                 f" on the first range; the rest on {amps(r.range_a)}")
        self._set_range(r.range_a)
        # Crossing into the blade the light goes; along increasing A or
        # B, an edge's step is this times the open side's sign.
        return first.median_a - r.first_dark.median_a

    def _coarse(self, r: LaserCommission, request: CommissionRequest,
                found: tuple[float, float], light: float,
                axes: tuple[int, ...]) -> float:
        """A coarse sweep `COARSE_HALF_MM` either side of where the
        light is, then a medium one round the edge it found: each edge
        to within a few readings. B needs A's edge first, to pass along
        B through the open quarter.
        `light` is what was read where it was found, and may be only
        part of the spot (found on an edge): a step at least half of it
        counts. Returns the full light, the largest step seen, for the
        passes that follow."""
        n = r.laser
        signs = self.pd.open_signs
        quarter = self.pd.chip_mm / 4
        for k in sorted(set(axes) | ({0} if 1 in axes else set())):
            other = (found[1 - k] if k == 0
                     else self._rough(r, 0) + signs[0] * quarter)
            start = self._clip(n, k, found[k] + signs[k] * COARSE_HALF_MM)
            wanted = found[k] - signs[k] * COARSE_HALF_MM
            end = self._clip(n, k, wanted)
            p = self._ranged_pass(r, k, start, end, other,
                                  request.coarse_feed_mm_s, light * signs[k],
                                  blade_side=-signs[k])
            r.coarse[k] = p
            if p.fit is None:
                short = (f"; laser {n} reaches only {AXES[k]} {end:.2f} on "
                         f"the carriage, so the blade may be beyond its "
                         f"reach" if abs(end - wanted) > 1e-6 else "")
                raise CommissionError(
                    f"laser {n}: no edge along {AXES[1 - k]} between "
                    f"{AXES[k]} {start:.2f} and {end:.2f} ({p.error}){short}")
            assert p.fit is not None
            # Each step is at least part of the light (a pass along an
            # edge's partner sees what that edge leaves): the largest.
            light = _larger(light, p.fit.step_a * signs[k])
            edge = p.fit.position_mm
            mid = self._ranged_pass(
                r, k, self._clip(n, k, edge + signs[k] * MEDIUM_HALF_MM),
                self._clip(n, k, edge - signs[k] * MEDIUM_HALF_MM), other,
                MEDIUM_FEED_MM_S, light * signs[k], blade_side=-signs[k])
            r.medium[k] = mid
            if mid.fit is None:
                r.warnings.append(f"the medium sweep along {AXES[k]} found "
                                  f"no edge ({mid.error}); the coarse one's "
                                  "is used")
            else:
                light = _larger(light, mid.fit.step_a * signs[k])
        return light

    def _rough(self, r: LaserCommission, k: int) -> float:
        """Where the edge along `k` is before the fine passes: the
        medium sweep's, or the coarse one's."""
        for passes in (r.medium, r.coarse):
            p = passes.get(k)
            if p is not None and p.fit is not None:
                return p.fit.position_mm
        raise CommissionError(f"laser {r.laser}: no edge along "
                              f"{AXES[1 - k]} yet")

    def _rough_width(self, r: LaserCommission, k: int) -> float:
        for passes in (r.medium, r.coarse):
            p = passes.get(k)
            if p is not None and p.fit is not None:
                return p.fit.width_mm
        raise CommissionError(f"laser {r.laser}: no edge along "
                              f"{AXES[1 - k]} yet")

    def _ranged_pass(self, r: LaserCommission, k: int, start: float,
                     end: float, other: float, feed: float,
                     step_a: float, blade_side: int = 0) -> EdgePass:
        """A pass, again on a larger range if it clips: the range was
        chosen from where the light was found, which may have been only
        the edge of the spot."""
        while True:
            p = self._pass(r.laser, k, start, end, other, feed, step_a,
                           at_least=True, blade_side=blade_side)
            assert self._range is not None
            limit = current_limit_for(self._range)
            peak = max((abs(i) for i in p.currents_a), default=0.0)
            larger = next_range(self._range)
            if peak < AT_LIMIT_SHARE * limit or larger is None:
                return p
            r.warnings.append(
                f"a pass along {AXES[k]} reached the {amps(self._range)} "
                f"range's limit; again on {amps(larger)}")
            self.say(f"laser {r.laser}: {r.warnings[-1]}")
            self._set_range(larger)
            r.range_a = larger

    def _fine(self, r: LaserCommission, request: CommissionRequest,
              light: float) -> None:
        """Up and down across each edge, the other axis in the middle of
        the open quarter: each edge's place, width and split."""
        n = r.laser
        signs = self.pd.open_signs
        quarter = self.pd.chip_mm / 4
        edge_at = {k: self._rough(r, k) for k in (0, 1)}
        width = {k: self._rough_width(r, k) for k in (0, 1)}
        for k in (0, 1):
            other = edge_at[1 - k] + signs[1 - k] * quarter
            half = max(FINE_HALF_MIN_MM, FINE_WIDTHS * width[k])
            lo = self._clip(n, k, edge_at[k] - half)
            hi = self._clip(n, k, edge_at[k] + half)
            # Now through the open quarter's middle: the whole spot, at
            # least what the coarse passes saw.
            up = self._ranged_pass(r, k, lo, hi, other,
                                   request.fine_feed_mm_s, light * signs[k])
            down = self._ranged_pass(r, k, hi, lo, other,
                                     request.fine_feed_mm_s, light * signs[k])
            fits = [p.fit for p in (up, down) if p.fit is not None]
            if len(fits) < 2:
                raise CommissionError(
                    f"laser {n}: the fine passes along {AXES[k]} found "
                    f"{len(fits)} edge(s) of 2 ({up.error or down.error})")
            assert up.fit is not None and down.fit is not None
            edge = Edge(k, (up.fit.position_mm + down.fit.position_mm) / 2,
                        (up.fit.width_mm + down.fit.width_mm) / 2,
                        up.fit.position_mm - down.fit.position_mm, (up, down))
            r.edges[k] = edge
            edge_at[k], width[k] = edge.position_mm, edge.width_mm
        corner = r.corner_mm
        assert corner is not None
        self.say(f"laser {n}: corner at A {corner[0]:.4f}, B {corner[1]:.4f}; "
                 f"10-90 % {r.edges[0].width_mm * 1000:.1f} um along A, "
                 f"{r.edges[1].width_mm * 1000:.1f} um along B")

    def _power(self, r: LaserCommission, request: CommissionRequest) -> None:
        """Power, warm by now, on the open quarter's middle, then the
        dark on the same range. Ends with the laser off."""
        n = r.laser
        d = self.devices
        signs = self.pd.open_signs
        quarter = self.pd.chip_mm / 4
        corner = r.corner_mm
        assert corner is not None and r.range_a is not None
        self._go(n, (corner[0] + signs[0] * quarter,
                     corner[1] + signs[1] * quarter))
        r.lit = self._read(n, request.read_s)
        d.laser.off()
        r.dark = self._read(0, request.read_s)
        self._check_voltage(r, r.dark, "dark")
        if r.lit.at_limit:
            r.warnings.append(f"the power reading reaches the "
                              f"{amps(r.range_a)} range's limit")
        if r.power_a is not None:
            self.say(f"laser {n}: power {amps(r.power_a)} on the "
                     f"{amps(r.range_a)} range")

    # ---- pieces ----

    def _sleep(self, seconds: float) -> None:
        until = self.clock.now() + seconds
        while self.clock.now() < until:
            check(self.halt)
            self.clock.sleep(min(0.5, until - self.clock.now()))
        check(self.halt)

    def _set_range(self, range_a: float) -> None:
        if range_a == self._range:
            return
        smu = self.devices.smu
        smu.prepare(bias_v=self._bias,
                    current_limit_a=current_limit_for(range_a),
                    current_range_a=range_a)
        smu.output_on()
        self._range = range_a

    def _measure(self) -> tuple[float, float, float]:
        """(time, volts, amps), the time the middle of the reading."""
        before = self.clock.now()
        v, i = self.devices.smu.measure(self.pd.channel)
        after = self.clock.now()
        pause = MIN_READ_INTERVAL_S - (after - before)
        if pause > 0:
            self.clock.sleep(pause)
        return (before + after) / 2, v, i

    def _read(self, laser: int, seconds: float,
              at_least: int = 3) -> Reading:
        values: list[float] = []
        volts: list[float] = []
        until = self.clock.now() + seconds
        while self.clock.now() < until or len(values) < at_least:
            check(self.halt)
            _, v, i = self._measure()
            volts.append(v)
            values.append(i)
        assert self._range is not None
        return summarise(laser, values, current_limit_for(self._range), volts)

    def _lit(self, reading: Reading, dark: Reading) -> bool:
        threshold = max(LIT_SIGMAS * dark.scatter_a, LIT_FLOOR_A)
        return abs(reading.median_a - dark.median_a) > threshold

    def _check_voltage(self, r: LaserCommission, reading: Reading,
                       what: str) -> None:
        v = reading.median_v
        if v is not None and abs(v - self._bias) > VOLTAGE_TOLERANCE_V:
            message = (f"channel {self.pd.channel} reports {v:+.4f} V at "
                       f"{self._bias:g} V during the {what} reading: the "
                       "offset state of 2026-10-29 (positions stand; the "
                       "dark on the same range removes it from the power)")
            r.warnings.append(message)
            self.say("! " + message)

    def _go(self, laser: int, point: tuple[float, float]) -> None:
        x, y, a, b = reach(self.machine, laser, point).xyab
        approach(self.devices.marlin, self.machine, x=x, y=y, a=a, b=b,
                 stop=self.halt)

    def _search(
        self, laser: int, middle: tuple[float, float], radius: float,
        dark: Reading,
    ) -> tuple[tuple[float, float], Reading] | None:
        """Outwards from `middle` on a square grid, ring by ring, until
        the channel shows light."""
        rings = int(math.ceil(radius / SEARCH_STEP_MM))
        for ring in range(1, rings + 1):
            for i in range(-ring, ring + 1):
                for j in range(-ring, ring + 1):
                    if max(abs(i), abs(j)) != ring:
                        continue
                    point = (middle[0] + i * SEARCH_STEP_MM,
                             middle[1] + j * SEARCH_STEP_MM)
                    try:
                        self._go(laser, point)
                    except OutOfReach:
                        continue
                    reading = self._read(laser, 0.0, SEARCH_READINGS)
                    if self._lit(reading, dark):
                        self.say(f"laser {laser}: light at A {point[0]:.2f}"
                                 f", B {point[1]:.2f}")
                        return point, reading
        return None

    def _clip(self, laser: int, axis: int, value: float) -> float:
        """`value` along `axis`, or the nearest point `laser` can reach."""
        lo, hi = span(self.machine, laser)[axis]
        margin = 1e-3
        return min(max(value, lo + margin), hi - margin)

    def _pass(self, laser: int, axis: int, start: float, end: float,
              other: float, feed: float, step_a: float,
              at_least: bool = False, blade_side: int = 0) -> EdgePass:
        """One pass along `axis` from carriage `start` to `end`, the other
        axis at `other`, reading all the way; the edge fitted. Only an
        edge whose step (along increasing position) is within half of
        `step_a` counts: noise on a flat stretch fits an edge too. With
        `at_least`, `step_a` may be only part of the light, and any step
        the same way and at least half of it counts. With `blade_side`
        (+1 or -1, the blade's way along the axis), only the readings
        from the brightest point that way are fitted: a pass that starts
        across another edge (the can window's) leaves it out."""
        d = self.devices
        name = AXES[axis].lower()
        mid = (start + end) / 2
        point = (mid, other) if axis == 0 else (other, mid)
        half = abs(end - start) / 2
        try:
            place = reach(self.machine, laser, point,
                          room_mm=(half, 0.0) if axis == 0 else (0.0, half))
        except OutOfReach as exc:
            raise CommissionError(
                f"laser {laser}: a pass along {AXES[axis]} is beyond its "
                f"reach ({exc})") from None
        x, y, a, b = place.xyab
        stage_mid = (a, b)[axis]
        offset = mid - stage_mid  # carriage minus stage, along `axis`
        targets = {"x": x, "y": y, "a": a, "b": b}
        targets[name] = start - offset
        approach(d.marlin, self.machine, stop=self.halt, **targets)
        s1 = end - offset
        direction = 1 if end > start else -1

        done: dict[str, Reply] = {}
        failed: list[BaseException] = []

        def wait() -> None:
            try:
                done["reply"] = d.marlin.wait_idle()
            except BaseException as exc:  # noqa: BLE001 - handed back
                failed.append(exc)

        d.marlin.move_to(feed_mm_s=feed, **{name: s1})
        waiter = threading.Thread(target=wait, name="edge-pass",
                                  daemon=True)
        waiter.start()
        times: list[float] = []
        currents: list[float] = []
        while waiter.is_alive():
            if self.halt.is_set():
                d.marlin.quickstop()
                waiter.join(timeout=5.0)
                raise RunStopped("stopped by the operator")
            t, _, i = self._measure()
            times.append(t)
            currents.append(i)
        waiter.join()
        if failed:
            raise failed[0]
        t_end = done["reply"].received_s
        stamps = np.asarray(times)
        stage = s1 - direction * feed * (t_end - stamps)
        low, high = sorted((start - offset, s1))
        keep = (stage >= low) & (stage <= high)
        positions = stage[keep] + offset
        values = np.asarray(currents)[keep]
        fitted_positions, fitted_values = positions, values
        if blade_side and len(values) >= SMOOTH_READINGS:
            # Brightest: most light, the light's sign being step_a's
            # along the way away from the blade.
            light_sign = 1.0 if step_a * -blade_side > 0 else -1.0
            kernel = np.ones(SMOOTH_READINGS) / SMOOTH_READINGS
            smooth = np.convolve(values * light_sign, kernel, mode="same")
            peak = positions[int(np.argmax(smooth))]
            side = (positions - peak) * blade_side >= 0
            fitted_positions, fitted_values = positions[side], values[side]
        fit: EdgeFit | None = None
        error = None
        try:
            fit = fit_edge(fitted_positions, fitted_values)
        except NoEdge as exc:
            error = str(exc)
        if fit is None:
            wrong = False
        elif at_least:
            wrong = (fit.step_a * step_a <= 0
                     or abs(fit.step_a) < EDGE_STEP_SHARE * abs(step_a))
        else:
            wrong = abs(fit.step_a - step_a) > EDGE_STEP_SHARE * abs(step_a)
        if fit is not None and wrong:
            error = (f"the step there, {amps(fit.step_a)}, is not the "
                     f"blade's {amps(step_a)}")
            fit = None
        return EdgePass(axis, direction, feed, tuple(positions.tolist()),
                        tuple(values.tolist()), fit, error)


def _larger(a: float, b: float) -> float:
    return b if abs(b) > abs(a) else a


def write_report(folder: Path, machine: MachineConfig,
                 result: CommissionResult, *, simulated: bool,
                 provenance: dict[str, Any]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "commission.json"
    data = {
        "schema": "multilbic-commission/1",
        "simulated": simulated,
        "provenance": provenance,
        "request": {"lasers": list(result.request.lasers),
                    "warmup_s": result.request.warmup_s,
                    "read_s": result.request.read_s,
                    "bias_v": result.request.bias_v,
                    "coarse_feed_mm_s": result.request.coarse_feed_mm_s,
                    "fine_feed_mm_s": result.request.fine_feed_mm_s,
                    "note": result.request.note,
                    "new_corner": result.request.new_corner},
        "lasers": {str(n): r.as_dict() for n, r in result.lasers.items()},
        "proposal": (None if result.proposal is None
                     else result.proposal.as_dict()),
        "error": result.error,
        "summary": result.lines(machine),
    }
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path


def folder_name(simulated: bool) -> str:
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_commission" + ("_sim" if simulated else "")


def estimate_s(request: CommissionRequest, lasers: Sequence[int]) -> float:
    """Roughly how long: homing, then per laser the warm-up, readings,
    and the sweeps (two coarse, two medium, four fine)."""
    per_laser = (request.warmup_s + 4 * request.read_s
                 + 2 * 2 * COARSE_HALF_MM / request.coarse_feed_mm_s
                 + 2 * 2 * MEDIUM_HALF_MM / MEDIUM_FEED_MM_S
                 + 4 * 2 * FINE_HALF_MIN_MM / request.fine_feed_mm_s
                 + 30.0)
    return 30.0 + per_laser * len(lasers)
