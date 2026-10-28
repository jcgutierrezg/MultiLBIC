"""
The sync error: where continuous rows put an edge, against where
step-and-measure finds it.

Step-and-measure finds an edge with no timing involved
(`multilbic.run.steps`); a continuous row finds it through the clock
map, its anchor and the motion model. Fitting the same edge in both
(`multilbic.scan.edges`) and comparing row by row, at the same B, gives
what the timing gets wrong.

How it splits, for a feature at `p` along A:

* Step-and-measure reaches every point moving up along A, so it sees the
  feature at `p + beta/2`, with `beta` the A backlash.
* A forward row is moving up too: `p + beta/2 + L v`, where `L` is
  whatever timing error is left (a stamp taken after the measurement
  makes `L` positive) and `v` the row's speed.
* A reverse row: `p - beta/2 - L v`.

So, against step-and-measure, forward rows sit `L v` away and reverse
rows `-(beta + L v)`. With two speeds or more, a straight-line fit gives
`L` and `beta` separately, where the serpentine alignment only ever sees
their sum (`beta + 2 L v`). A constant offset common to both directions
(`centre`) would be something else again: the two runs not seeing the
stage in the same place.

When the session repeats step-and-measure at the end, the difference
between the two is the drift over the session (thermal, the stage
creeping), which limits what any of this can resolve.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from multilbic.scan.edges import EdgeShift, RowEdge, edge_shift, fit_rows
from multilbic.scan.mapping import BASELINE_ROW, build_map
from multilbic.store.runfile import RunFile

#: A continuous row is compared only within this share of a pitch of
#: the step rows' span in B: beyond, the reference would be guessed.
B_MARGIN_PITCH = 0.5


@dataclass(frozen=True)
class PointRow:
    """One step-and-measure row, averaged per point."""

    row: int
    b_mm: float
    a_mm: np.ndarray
    mean_a: np.ndarray
    #: Standard error of each point's mean.
    sem_a: np.ndarray
    count: np.ndarray


def is_steps(run: RunFile) -> bool:
    return run.header.get("mode") == "steps"


def point_rows(run: RunFile) -> list[PointRow]:
    """A step-and-measure file's points: one mean per point, with the
    laser-off baseline subtracted."""
    c = run.columns
    row = c["row"].astype(int)
    current = c["current_a"]
    base = row == BASELINE_ROW
    offset = float(np.mean(current[base])) if base.any() else 0.0
    out = []
    for k in sorted(set(row[row >= 0].tolist())):
        mine = row == k
        a = np.round(c["a_mm"][mine], 6)
        b = float(np.median(c["b_mm"][mine]))
        values = current[mine] - offset
        points, index = np.unique(a, return_inverse=True)
        count = np.bincount(index)
        mean = np.bincount(index, weights=values) / count
        square = np.bincount(index, weights=values**2) / count
        sem = np.sqrt(np.maximum(square - mean**2, 0.0)
                      / np.maximum(count - 1, 1))
        out.append(PointRow(k, b, points, mean, sem, count))
    return out


def step_edges(
    run: RunFile, a_range: tuple[float, float] | None = None
) -> tuple[list[RowEdge], dict[int, str]]:
    """The edge in each step-and-measure row, along A in machine mm."""
    return fit_rows(
        [(r.row, 0, r.b_mm, r.a_mm, r.mean_a) for r in point_rows(run)],
        x_range=a_range,
    )


@dataclass(frozen=True)
class ScanEdges:
    edges: list[RowEdge]
    failed: dict[int, str]
    #: From the edges: forward rows minus reverse rows.
    shift: EdgeShift | None
    #: What the map's own serpentine alignment says, for comparison.
    alignment_shift_mm: float | None


def scan_edges(
    run: RunFile, a_range: tuple[float, float] | None = None
) -> ScanEdges:
    """The edge in each continuous row, along A in machine mm, from the
    rows' timing alone (no serpentine correction)."""
    data = run.scan_data()
    raw = build_map(data, align=False)
    origin_a = data.frame.origin_ab_mm[0]
    b = {anchor.index: anchor.b_mm for anchor in data.anchors}
    edges, failed = fit_rows(
        [(r.index, r.direction, b[r.index], r.u_mm + origin_a, r.values)
         for r in raw.rows if r.u_mm.size],
        x_range=a_range,
    )
    aligned = build_map(data).alignment
    return ScanEdges(
        edges, failed, edge_shift(edges),
        aligned.shift_mm if aligned.found else None,
    )


@dataclass(frozen=True)
class Offset:
    """Rows of one direction against the reference, robustly."""

    median_mm: float
    spread_mm: float
    count: int

    def as_dict(self) -> dict[str, float | int]:
        return {"offset_um": self.median_mm * 1000,
                "spread_um": self.spread_mm * 1000, "count": self.count}


def _offset(values: list[float]) -> Offset | None:
    if not values:
        return None
    a = np.asarray(values)
    median = float(np.median(a))
    return Offset(median, float(1.4826 * np.median(np.abs(a - median))),
                  len(values))


@dataclass(frozen=True)
class PassResult:
    """One continuous pass against step-and-measure."""

    name: str
    speed_mm_s: float
    forward: Offset | None
    reverse: Offset | None
    edges: ScanEdges

    @property
    def lag_ms(self) -> float | None:
        """`L` from this pass alone, assuming no backlash."""
        if self.forward is None or self.reverse is None:
            return None
        return ((self.forward.median_mm - self.reverse.median_mm) / 2
                / self.speed_mm_s * 1000)

    def as_dict(self) -> dict[str, Any]:
        e = self.edges
        return {
            "name": self.name,
            "speed_mm_s": self.speed_mm_s,
            "forward": self.forward.as_dict() if self.forward else None,
            "reverse": self.reverse.as_dict() if self.reverse else None,
            "edge_shift": e.shift.as_dict() if e.shift else None,
            "alignment_shift_um": (None if e.alignment_shift_mm is None
                                   else e.alignment_shift_mm * 1000),
            "median_width_um": _median_width_um(e.edges),
            "rows_fitted": len(e.edges),
            "rows_failed": {str(k): v for k, v in e.failed.items()},
        }


def _median_width_um(edges: list[RowEdge]) -> float | None:
    if not edges:
        return None
    return float(np.median([e.fit.width_mm for e in edges])) * 1000


class Reference:
    """Step-and-measure's edge as a function of B: per row, or the mean
    of two passes where both have the row."""

    def __init__(self, passes: list[list[RowEdge]], pitch_mm: float):
        by_b: dict[float, list[float]] = {}
        for edges in passes:
            for e in edges:
                by_b.setdefault(round(e.b_mm, 4), []).append(
                    e.fit.position_mm)
        if not by_b:
            raise ValueError("step-and-measure found no edge in any row")
        self.b = np.array(sorted(by_b))
        self.a = np.array([float(np.mean(by_b[b])) for b in self.b])
        self.margin = B_MARGIN_PITCH * pitch_mm

    def covers(self, b: float) -> bool:
        return self.b[0] - self.margin <= b <= self.b[-1] + self.margin

    def at(self, b: float) -> float:
        return float(np.interp(b, self.b, self.a))


def compare_pass(
    name: str, speed_mm_s: float, edges: ScanEdges, reference: Reference
) -> PassResult:
    forward, reverse = [], []
    for e in edges.edges:
        if not reference.covers(e.b_mm):
            continue
        d = e.fit.position_mm - reference.at(e.b_mm)
        (forward if e.direction > 0 else reverse).append(d)
    return PassResult(name, speed_mm_s, _offset(forward), _offset(reverse),
                      edges)


@dataclass(frozen=True)
class SpeedFit:
    """`forward = L v + forward_mm`, `reverse = -L v + reverse_mm`, over
    every pass: the timing error and what is left at zero speed."""

    lag_ms: float
    forward_mm: float
    reverse_mm: float
    #: RMS of what the lines leave, over the passes' medians.
    residual_mm: float
    passes: int

    @property
    def backlash_mm(self) -> float:
        """Forward minus reverse at zero speed: `beta`."""
        return self.forward_mm - self.reverse_mm

    def as_dict(self) -> dict[str, float | int]:
        return {
            "lag_ms": self.lag_ms,
            "forward_at_zero_um": self.forward_mm * 1000,
            "reverse_at_zero_um": self.reverse_mm * 1000,
            "backlash_um": self.backlash_mm * 1000,
            "residual_um": self.residual_mm * 1000,
            "passes": self.passes,
        }


def fit_speeds(results: list[PassResult]) -> SpeedFit | None:
    """None with fewer than two speeds: one speed can't tell a timing
    error from backlash."""
    rows, values = [], []
    speeds = set()
    for r in results:
        if r.forward is not None:
            rows.append([r.speed_mm_s, 1.0, 0.0])
            values.append(r.forward.median_mm)
            speeds.add(r.speed_mm_s)
        if r.reverse is not None:
            rows.append([-r.speed_mm_s, 0.0, 1.0])
            values.append(r.reverse.median_mm)
            speeds.add(r.speed_mm_s)
    if len(speeds) < 2:
        return None
    m, y = np.array(rows), np.array(values)
    solution, *_ = np.linalg.lstsq(m, y, rcond=None)
    lag_s, forward, reverse = (float(v) for v in solution)
    left = y - m @ solution
    return SpeedFit(lag_s * 1000, forward, reverse,
                    float(np.sqrt(np.mean(left**2))), len(results))


@dataclass(frozen=True)
class Drift:
    """The second step-and-measure pass minus the first, over the rows
    both found."""

    median_mm: float
    spread_mm: float
    count: int

    def as_dict(self) -> dict[str, float | int]:
        return {"drift_um": self.median_mm * 1000,
                "spread_um": self.spread_mm * 1000, "count": self.count}


def drift(first: list[RowEdge], last: list[RowEdge]) -> Drift | None:
    before = {e.row: e.fit.position_mm for e in first}
    d = [e.fit.position_mm - before[e.row] for e in last if e.row in before]
    if not d:
        return None
    a = np.asarray(d)
    median = float(np.median(a))
    return Drift(median, float(1.4826 * np.median(np.abs(a - median))),
                 len(d))
