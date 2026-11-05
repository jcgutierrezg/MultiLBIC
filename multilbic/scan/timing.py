"""
When each sample was taken, and so where the stage was.

Three pieces, matching the plan in `docs/architecture.md` (option B):

* **The motion model.** A row is one straight `G1` along A that starts
  and ends at rest: a trapezoid (or a triangle) set by the feedrate and
  the acceleration. This is written here independently of
  `multilbic.sim.motion`, on purpose. The simulator and the scan each
  have their own idea of how Marlin moves, so a test can catch either
  one being wrong instead of confirming that the two agree.
* **The clock map.** Each streamed sample carries a timestamp from the
  miniSMU's clock and the host time it arrived. Arrival is always after
  the measurement, so the smallest gap between the two in each stretch
  of time is the best estimate of the clocks' offset there; a straight
  line through those minima tracks the offset and the drift between
  the clocks. The instrument's `set_time()` is never relied on.
* **Row anchors.** A row ends when Marlin's `ok` to the `M400` after it
  arrives. That is the anchor: the row's start is the end minus the
  modelled duration. Most of the time the `ok` comes a steady time
  after the row's `G1` was sent, the move plus 93-96 ms (Marlin's
  first-move delay and the round trip; bench, 72 run files, 2026-10-23
  to 11-05), steady to half a millisecond in each file. But for a
  stretch of rows, sometimes a whole map, it comes 20-40 ms late (in
  about one map in six). The rows are then placed 20-40 ms late, which
  at 4 mm/s turned the serpentine shift from +130 to as low as -196 µm
  (2026-11-05). The move itself had started and ended on time: placed
  from the send instead, the same maps gave the usual shift and their
  forward and reverse rows met on the cell's edge.
  `settle_late_replies` does that for every late row: a reply later
  than the file's usual delay, by more than `LATE_REPLY_S`, is replaced
  by the send time plus the usual delay plus the move. The usual delay
  is the file's own, from its quickest replies, unless even those are
  late against the machine's on-time delay (`[ab] row_reply_ms`): in
  one map every row was 20-40 ms late, its quickest included.

What is left uncorrected here is constant: the `ok`'s latency and the
smallest stream delay. A constant time error moves forward rows one way
and reverse rows the other, so the serpentine alignment
(`multilbic.scan.alignment`) measures and removes it, together with
backlash.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np

#: Marlin's DEFAULT_ACCELERATION on this machine (docs/hardware.md). The
#: acceleration of a move is the lower of this and each axis's own limit.
MARLIN_DEFAULT_ACCEL_MM_S2 = 100.0
#: Marlin waits this long before starting a move into an empty planner
#: (BLOCK_DELAY_FOR_1ST_MOVE); measured 113-135 ms per move with the
#: trapezoid, on the bench. Used for time estimates only.
FIRST_MOVE_DELAY_S = 0.100
#: The clock map's stretch of time per minimum.
CLOCK_WINDOW_S = 1.0
#: A row's `ok` this much later than its file's usual send-to-reply
#: delay is late (`settle_late_replies`). On time, the delay is steady
#: to about half a millisecond in a file; late ones were 20-40 ms over.
LATE_REPLY_S = 0.004
#: The on-time delay for run files from before it was recorded in their
#: header: the bench's (`[ab] row_reply_ms`, machine.toml).
BENCH_ROW_REPLY_S = 0.0935


@dataclass(frozen=True)
class Trapezoid:
    """A move from rest to rest along a straight line."""

    distance_mm: float
    feed_mm_s: float
    accel_mm_s2: float

    def __post_init__(self) -> None:
        if self.distance_mm < 0:
            raise ValueError("distance must be >= 0")
        if self.feed_mm_s <= 0 or self.accel_mm_s2 <= 0:
            raise ValueError("feed and acceleration must be > 0")

    @property
    def _ramp(self) -> tuple[float, float]:
        """(peak speed, time spent accelerating)."""
        full_ramp = self.feed_mm_s**2 / self.accel_mm_s2
        if full_ramp >= self.distance_mm:
            t = math.sqrt(self.distance_mm / self.accel_mm_s2)
            return self.accel_mm_s2 * t, t
        return self.feed_mm_s, self.feed_mm_s / self.accel_mm_s2

    @property
    def duration_s(self) -> float:
        peak, t_ramp = self._ramp
        if peak == 0:
            return 0.0
        ramp_mm = peak * t_ramp  # both ramps together
        return 2 * t_ramp + (self.distance_mm - ramp_mm) / peak

    def distance_at(self, t: np.ndarray | float) -> np.ndarray:
        """Distance travelled `t` seconds after the move starts."""
        t = np.clip(np.asarray(t, dtype=float), 0.0, self.duration_s)
        peak, t_ramp = self._ramp
        a = self.accel_mm_s2
        total = self.duration_s
        accelerating = 0.5 * a * t * t
        cruising = 0.5 * peak * t_ramp + peak * (t - t_ramp)
        left = total - t
        braking = self.distance_mm - 0.5 * a * left * left
        return np.where(
            t < t_ramp,
            accelerating,
            np.where(t <= total - t_ramp, cruising, braking),
        )


def axis_accel(axis_max_accel_mm_s2: float) -> float:
    """The acceleration Marlin uses for a move along one axis."""
    return min(axis_max_accel_mm_s2, MARLIN_DEFAULT_ACCEL_MM_S2)


@dataclass(frozen=True)
class RowMotion:
    """One row's move along A, placed in host time by its anchor."""

    a_from_mm: float
    a_to_mm: float
    profile: Trapezoid
    #: Host time the move ended (the `M400` ok's arrival).
    end_s: float

    @classmethod
    def from_anchor(
        cls,
        a_from_mm: float,
        a_to_mm: float,
        feed_mm_s: float,
        accel_mm_s2: float,
        end_s: float,
    ) -> RowMotion:
        profile = Trapezoid(abs(a_to_mm - a_from_mm), feed_mm_s, accel_mm_s2)
        return cls(a_from_mm, a_to_mm, profile, end_s)

    @property
    def start_s(self) -> float:
        return self.end_s - self.profile.duration_s

    @property
    def direction(self) -> int:
        return 1 if self.a_to_mm >= self.a_from_mm else -1

    def a_at(self, host_s: np.ndarray | float) -> np.ndarray:
        """A position at host time(s) `host_s`."""
        travelled = self.profile.distance_at(np.asarray(host_s) - self.start_s)
        return self.a_from_mm + self.direction * travelled


@dataclass(frozen=True)
class RowAnchor:
    """What the run records about a row as it happens: the move it
    asked Marlin for, and the host times of the move's `G1` being sent
    and of the `M400` ok that says it ended."""

    index: int
    b_mm: float
    a_from_mm: float
    a_to_mm: float
    feed_mm_s: float
    accel_mm_s2: float
    sent_s: float
    end_s: float

    def motion(self) -> RowMotion:
        return RowMotion.from_anchor(
            self.a_from_mm, self.a_to_mm, self.feed_mm_s,
            self.accel_mm_s2, self.end_s,
        )


def reply_delays(anchors: Sequence[RowAnchor]) -> np.ndarray:
    """Each row's time from its `G1` being sent to its `M400`'s ok,
    minus the modelled move, in seconds."""
    return np.array([
        a.end_s - a.sent_s - a.motion().profile.duration_s for a in anchors
    ])


def settle_late_replies(
    anchors: Sequence[RowAnchor],
    on_time_s: float = BENCH_ROW_REPLY_S,
) -> tuple[RowAnchor, ...]:
    """The anchors, with each late reply replaced by the send time plus
    the file's usual delay plus the move. The usual delay is the median
    of the replies within `LATE_REPLY_S` of the quickest; if even the
    quickest is late against `on_time_s`, the machine's on-time delay,
    that is used."""
    if not anchors:
        return tuple(anchors)
    delays = reply_delays(anchors)
    quickest = float(delays.min())
    if quickest > on_time_s + LATE_REPLY_S:
        usual = on_time_s
    else:
        usual = float(np.median(delays[delays <= quickest + LATE_REPLY_S]))
    out = []
    for anchor, delay in zip(anchors, delays, strict=True):
        if delay > usual + LATE_REPLY_S:
            anchor = replace(anchor, end_s=anchor.end_s - (delay - usual))
        out.append(anchor)
    return tuple(out)


@dataclass(frozen=True)
class ClockMap:
    """host_s = device_s + offset_s + drift * (device_s - reference_s).

    `drift` is the host clock's rate relative to the device's, minus one
    (1e-4 is 100 ppm)."""

    offset_s: float
    drift: float
    reference_s: float

    def to_host(self, device_ms: np.ndarray | float) -> np.ndarray:
        d = np.asarray(device_ms, dtype=float) / 1000.0
        return d + self.offset_s + self.drift * (d - self.reference_s)

    def as_dict(self) -> dict[str, float]:
        return {
            "offset_s": self.offset_s,
            "drift_ppm": self.drift * 1e6,
            "reference_s": self.reference_s,
        }

    @classmethod
    def from_dict(cls, data: dict[str, float]) -> ClockMap:
        return cls(data["offset_s"], data["drift_ppm"] * 1e-6,
                   data["reference_s"])


def fit_clock(
    device_ms: np.ndarray,
    host_s: np.ndarray,
    window_s: float = CLOCK_WINDOW_S,
) -> ClockMap:
    """Fit the clock map from every sample's two timestamps.

    Each window of device time contributes its smallest
    `host - device` gap, the sample that waited least on its way to the
    host. A line through those minima gives offset and drift. With
    fewer than two windows only the offset is fitted.
    """
    tracker = ClockTracker(window_s)
    tracker.add(device_ms, host_s)
    return tracker.fit()


class ClockTracker:
    """The clock map kept up to date as samples stream in, holding only
    each window's minimum rather than every sample."""

    def __init__(self, window_s: float = CLOCK_WINDOW_S):
        self.window_s = window_s
        self.reference_s: float | None = None
        #: window -> (smallest host - device gap, its device time)
        self._minima: dict[int, tuple[float, float]] = {}

    def add(self, device_ms: np.ndarray, host_s: np.ndarray) -> None:
        device_s = np.asarray(device_ms, dtype=float) / 1000.0
        host = np.asarray(host_s, dtype=float)
        if device_s.size == 0:
            return
        if self.reference_s is None:
            self.reference_s = float(device_s.min())
        gap = host - device_s
        windows = np.floor(
            (device_s - self.reference_s) / self.window_s
        ).astype(int)
        order = np.lexsort((gap, windows))
        first = np.r_[True, np.diff(windows[order]) != 0]
        for i in order[first]:
            w, g = int(windows[i]), float(gap[i])
            if w not in self._minima or g < self._minima[w][0]:
                self._minima[w] = (g, float(device_s[i]))

    def fit(self) -> ClockMap:
        if self.reference_s is None:
            raise ValueError("no samples to fit the clock map to")
        values = list(self._minima.values())
        ys = np.array([g for g, _ in values])
        xs = np.array([x for _, x in values])
        return _fit_minima(xs, ys, self.reference_s)


def _fit_minima(xs: np.ndarray, ys: np.ndarray, reference: float) -> ClockMap:
    if xs.size < 2:
        return ClockMap(float(ys.min()), 0.0, reference)
    # Every gap is at least the true offset, so the line wanted is the
    # lower bound of the minima: of the lines through two neighbouring
    # points of their lower convex hull, the one closest to all the
    # points. A window where the host was slow to read sits above it
    # and pulls on nothing, where a least-squares line would tilt.
    order = np.lexsort((ys, xs))
    x, y = xs[order] - reference, ys[order]
    hull = _lower_hull(x, y)
    best: tuple[float, float, float] | None = None
    for i, j in zip(hull, hull[1:], strict=False):
        slope = (y[j] - y[i]) / (x[j] - x[i])
        intercept = y[i] - slope * x[i]
        cost = float(np.sum(y - (slope * x + intercept)))
        if best is None or cost < best[0]:
            best = (cost, float(slope), float(intercept))
    if best is None:  # every minimum at the same device time
        return ClockMap(float(y.min()), 0.0, reference)
    return ClockMap(best[2], best[1], reference)


def _lower_hull(x: np.ndarray, y: np.ndarray) -> list[int]:
    """Indices of the lower convex hull of points sorted by x."""
    hull: list[int] = []
    for k in range(x.size):
        while len(hull) >= 2:
            i, j = hull[-2], hull[-1]
            cross = (x[j] - x[i]) * (y[k] - y[i]) - (y[j] - y[i]) * (x[k] - x[i])
            if cross > 0:
                break
            hull.pop()
        if hull and x[hull[-1]] == x[k]:
            continue
        hull.append(k)
    return hull
