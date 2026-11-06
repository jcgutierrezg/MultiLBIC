"""
The viewer's arithmetic, without Tk: where the cursor is on the sample,
the value there, a line profile, and colour limits.

A map is drawn turned to `[display]` (`store/image.draw_map`): with u
horizontal the plot's x is u and its y is v; with u vertical, x is v
and y is u. The axes keep true millimetres, only their direction
changes, so turning a plot point back into the sample's u, v is a swap
at most.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from multilbic.store.runfolder import SharedGrid

#: Auto colour limits: these percentiles of the map's values, so a few
#: wild pixels don't wash the rest out.
AUTO_PERCENTILES = (1.0, 99.0)


def u_horizontal(view: tuple[str, str]) -> bool:
    return view[0] in ("left", "right")


def to_uv(view: tuple[str, str], x: float, y: float) -> tuple[float, float]:
    """A point on the drawn map (the plot's x, y) as the sample's u, v."""
    return (x, y) if u_horizontal(view) else (y, x)


def to_xy(view: tuple[str, str], u: float, v: float) -> tuple[float, float]:
    """The sample's u, v as a point on the drawn map."""
    return (u, v) if u_horizontal(view) else (v, u)


def pixel_at(grid: SharedGrid, u: float, v: float) -> tuple[int, int] | None:
    """The (row, column) of the pixel holding u, v, or None off the map."""
    j = math.floor(u / grid.pixel_mm)
    k = math.floor(v / grid.pitch_mm)
    n_v, n_u = grid.shape
    if 0 <= j < n_u and 0 <= k < n_v:
        return k, j
    return None


def value_at(values: np.ndarray, grid: SharedGrid, u: float,
             v: float) -> float | None:
    """The map's value at u, v (NaN for an empty pixel), None off it."""
    at = pixel_at(grid, u, v)
    return None if at is None else float(values[at])


@dataclass(frozen=True)
class Profile:
    """Values along a straight line on the sample."""

    start_uv: tuple[float, float]
    end_uv: tuple[float, float]
    #: Distance from the start, mm.
    distance_mm: np.ndarray
    #: The pixel each point falls in; NaN off the map or empty.
    values: np.ndarray

    @property
    def length_mm(self) -> float:
        return float(math.dist(self.start_uv, self.end_uv))


def profile(values: np.ndarray, grid: SharedGrid,
            start_uv: tuple[float, float],
            end_uv: tuple[float, float]) -> Profile:
    """The map along the line from `start_uv` to `end_uv`, a point every
    half of the finer of the pixel and the pitch, so no pixel the line
    crosses is skipped. Each point takes its pixel's value."""
    length = math.dist(start_uv, end_uv)
    step = min(grid.pixel_mm, grid.pitch_mm) / 2
    n = max(2, math.ceil(length / step) + 1)
    t = np.linspace(0.0, 1.0, n)
    u = start_uv[0] + t * (end_uv[0] - start_uv[0])
    v = start_uv[1] + t * (end_uv[1] - start_uv[1])
    cols = np.floor(u / grid.pixel_mm).astype(int)
    rows = np.floor(v / grid.pitch_mm).astype(int)
    n_v, n_u = grid.shape
    inside = (cols >= 0) & (cols < n_u) & (rows >= 0) & (rows < n_v)
    out = np.full(n, np.nan)
    out[inside] = values[rows[inside], cols[inside]]
    return Profile(start_uv, end_uv, t * length, out)


#: The units a map can be shown in, largest first: (name, amps per unit).
UNITS = (("mA", 1e-3), ("µA", 1e-6), ("nA", 1e-9), ("pA", 1e-12))


def display_unit(values: np.ndarray) -> tuple[str, float]:
    """The largest unit in which the map's biggest value is at least 1:
    a cell giving 0.8 mA is shown in µA (800), not mA (0.8)."""
    finite = np.abs(values[np.isfinite(values)])
    biggest = float(finite.max()) if finite.size else 0.0
    for name, scale in UNITS:
        if biggest >= scale:
            return name, scale
    return UNITS[-1]


def auto_limits(values: np.ndarray,
                percentiles: tuple[float, float] = AUTO_PERCENTILES,
                ) -> tuple[float, float] | None:
    """Colour limits holding all but the extreme percent at either end;
    None for a map with no values."""
    finite = values[np.isfinite(values)]
    if not finite.size:
        return None
    lo, hi = np.percentile(finite, percentiles)
    return _widened(float(lo), float(hi))


def full_limits(values: np.ndarray) -> tuple[float, float] | None:
    """From the smallest value to the largest."""
    finite = values[np.isfinite(values)]
    if not finite.size:
        return None
    return _widened(float(finite.min()), float(finite.max()))


def _widened(lo: float, hi: float) -> tuple[float, float]:
    """A flat map still gets a range to draw in."""
    if hi > lo:
        return lo, hi
    pad = abs(lo) * 1e-3 or 1e-12
    return lo - pad, hi + pad
