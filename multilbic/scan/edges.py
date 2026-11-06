"""
Where an edge is along a row, and how sharp: an error-function fit.

A round Gaussian spot crossing a straight edge gives a current that
follows the spot's cumulative profile, an error function. Its 50 % point
is where the spot's centre crosses the edge, and its width is the spot's
width along the row. So one fit gives both what the timing checks need
(the edge's position, row by row) and what a knife-edge measurement
needs (the spot's size).

The model, along `x` (mm):

    y = low + slope * (x - x0) + step * Phi((x - x0) / sigma)

`Phi` is the standard normal cumulative distribution; `step` is
negative for a falling edge. `slope` takes up a background that leans
(on the test cell, current rises towards the contact), so the plateaus
need not be flat. The 10-90 % width is `2.563 * sigma`, the figure
`spot_um` in machine.toml uses.

Fitting is Levenberg-Marquardt on all five numbers, with `sigma` fitted
as its logarithm so it stays positive. The start comes from the data:
the profile is binned and smoothed, its steepest point is the edge (or
the middle of the window given), and the plateaus either side give the
levels. A first fit over the whole row places the edge; a second, over
a window a few widths either side of it, is the answer, so far-off
features and the background's curvature matter less.

numpy only: SMUniversal's scipy is dropped from the install
(pyproject.toml).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

#: 10-90 % width of an error-function edge, in units of its sigma.
WIDTH_10_90_PER_SIGMA = 2 * 1.2815515655446004
#: The second fit uses this many 10-90 % widths either side of the edge,
#: and at least `MIN_HALF_WINDOW_MM`.
WINDOW_WIDTHS = 4.0
MIN_HALF_WINDOW_MM = 0.03
#: Bins for the starting guess, across the data's range.
GUESS_BINS = 400
#: An edge must stand this many noise levels above the scatter to count.
MIN_STEP_TO_NOISE = 5.0
MAX_ITERATIONS = 100

_SQRT2 = math.sqrt(2.0)
_INV_SQRT_2PI = 1.0 / math.sqrt(2.0 * math.pi)
_erf = np.frompyfunc(math.erf, 1, 1)


def phi(z: np.ndarray) -> np.ndarray:
    """The standard normal cumulative distribution."""
    return 0.5 * (1.0 + _erf(np.asarray(z, dtype=float) / _SQRT2).astype(float))


@dataclass(frozen=True)
class EdgeFit:
    #: The 50 % point, mm: where the spot's centre crosses the edge.
    position_mm: float
    #: The spot's standard deviation along the row, mm.
    sigma_mm: float
    #: Current before the edge (at `position_mm`, without the step), A.
    low_a: float
    #: The step across the edge, A: negative for a falling edge.
    step_a: float
    slope_a_per_mm: float
    #: Standard errors from the fit's covariance.
    position_err_mm: float
    sigma_err_mm: float
    #: RMS of what the model leaves.
    residual_a: float
    n: int

    @property
    def width_mm(self) -> float:
        """The 10-90 % width."""
        return WIDTH_10_90_PER_SIGMA * self.sigma_mm

    @property
    def width_err_mm(self) -> float:
        return WIDTH_10_90_PER_SIGMA * self.sigma_err_mm

    @property
    def rising(self) -> bool:
        return self.step_a > 0

    def model(self, x: np.ndarray) -> np.ndarray:
        return _model(
            np.asarray(x, dtype=float),
            np.array([self.position_mm, math.log(self.sigma_mm),
                      self.low_a, self.step_a, self.slope_a_per_mm]),
        )

    def as_dict(self) -> dict[str, float | int]:
        return {
            "position_mm": self.position_mm,
            "position_err_mm": self.position_err_mm,
            "width_um": self.width_mm * 1000,
            "width_err_um": self.width_err_mm * 1000,
            "sigma_um": self.sigma_mm * 1000,
            "low_a": self.low_a,
            "step_a": self.step_a,
            "slope_a_per_mm": self.slope_a_per_mm,
            "residual_a": self.residual_a,
            "n": self.n,
        }


class NoEdge(ValueError):
    """The data hold no edge that can be fitted."""


def fit_edge(
    x: np.ndarray,
    y: np.ndarray,
    *,
    x_range: tuple[float, float] | None = None,
    near: float | None = None,
    start_mm: float | None = None,
) -> EdgeFit:
    """Fit one edge to samples `y` at positions `x` (mm).

    `x_range` keeps only samples inside it. Without `near`, the edge is
    the steepest step in what is left; with it, the clear step closest
    to `near`, fitted between its neighbours, for a profile with several
    clean edges (fingers). In noise, prefer `x_range`: noise has steps
    of its own for `near` to find. `start_mm` starts the fit at that
    position instead of searching, for an edge known from elsewhere. Raises `NoEdge` if nothing stands out of the
    noise or the fit does not settle inside the data."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    keep = np.isfinite(x) & np.isfinite(y)
    if x_range is not None:
        keep &= (x >= min(x_range)) & (x <= max(x_range))
    x, y = x[keep], y[keep]
    if x.size < 8:
        raise NoEdge(f"{x.size} samples: too few to fit an edge")
    order = np.argsort(x, kind="stable")
    x, y = x[order], y[order]

    start, (w_lo, w_hi) = _guess(x, y, near, start_mm)
    with np.errstate(all="ignore"):
        try:
            own = (x >= w_lo) & (x <= w_hi)
            first = _levenberg_marquardt(x[own], y[own], start)
            half = max(
                WINDOW_WIDTHS * WIDTH_10_90_PER_SIGMA * math.exp(first[1]),
                MIN_HALF_WINDOW_MM)
            inside = np.abs(x - first[0]) <= half
            if inside.sum() >= 8:
                final = _levenberg_marquardt(x[inside], y[inside], first)
                xs, ys = x[inside], y[inside]
            else:
                final, xs, ys = first, x, y
            return _result(xs, ys, final)
        except (OverflowError, FloatingPointError, ValueError) as exc:
            if isinstance(exc, NoEdge):
                raise
            raise NoEdge(f"the fit did not settle: {exc}") from None


def _model(x: np.ndarray, p: np.ndarray) -> np.ndarray:
    x0, log_sigma, low, step, slope = p
    z = (x - x0) / math.exp(log_sigma)
    return low + slope * (x - x0) + step * phi(z)


def _jacobian(x: np.ndarray, p: np.ndarray) -> np.ndarray:
    x0, log_sigma, _, step, slope = p
    sigma = math.exp(log_sigma)
    z = (x - x0) / sigma
    density = _INV_SQRT_2PI * np.exp(-0.5 * z * z)
    return np.column_stack([
        -slope - step * density / sigma,  # d/dx0
        -step * density * z,  # d/dlog(sigma)
        np.ones_like(x),  # d/dlow
        phi(z),  # d/dstep
        x - x0,  # d/dslope
    ])


def _levenberg_marquardt(
    x: np.ndarray, y: np.ndarray, start: np.ndarray
) -> np.ndarray:
    p = start.astype(float).copy()
    # The width stays between a tenth of the finest spacing and the
    # data's span: outside that the model is flat or a step, and the
    # fit can wander off.
    spacing = np.diff(x)
    finest = float(spacing[spacing > 0].min()) if (spacing > 0).any() else 1e-4
    log_lo = math.log(max(finest / 10, 1e-6))
    log_hi = math.log(max(float(x[-1] - x[0]), finest))
    p[1] = min(max(p[1], log_lo), log_hi)
    residual = y - _model(x, p)
    cost = float(residual @ residual)
    damping = 1e-3
    for _ in range(MAX_ITERATIONS):
        jac = _jacobian(x, p)
        normal = jac.T @ jac
        gradient = jac.T @ residual
        scale = np.diag(normal).copy()
        scale[scale == 0] = 1.0
        improved = False
        for _ in range(20):
            try:
                delta = np.linalg.solve(
                    normal + damping * np.diag(scale), gradient)
            except np.linalg.LinAlgError:
                damping *= 10
                continue
            trial = p + delta
            trial[1] = min(max(trial[1], log_lo), log_hi)
            trial_residual = y - _model(x, trial)
            trial_cost = float(trial_residual @ trial_residual)
            if trial_cost < cost:
                improved = True
                break
            damping *= 10
        if not improved:
            break
        small = abs(cost - trial_cost) <= 1e-12 * max(cost, 1e-300)
        p, residual, cost = trial, trial_residual, trial_cost
        damping = max(damping / 10, 1e-12)
        if small or np.all(np.abs(delta) <= 1e-10 * (np.abs(p) + 1e-12)):
            break
    return p


#: With `near`, a step this share of the steepest one is a candidate.
NEAR_CANDIDATE_SHARE = 0.2


def _guess(
    x: np.ndarray, y: np.ndarray, near: float | None,
    start_mm: float | None = None,
) -> tuple[np.ndarray, tuple[float, float]]:
    """A starting point for the fit, and the stretch of data around the
    edge to start on: the whole row, or with `near`, up to halfway to
    the next steep step either side."""
    lo, hi = float(x[0]), float(x[-1])
    if hi - lo <= 0:
        raise NoEdge("all samples are at one position")
    bins = min(GUESS_BINS, max(8, x.size // 4))
    edges = np.linspace(lo, hi, bins + 1)
    index = np.clip(np.searchsorted(edges, x, side="right") - 1, 0, bins - 1)
    counts = np.bincount(index, minlength=bins)
    sums = np.bincount(index, weights=y, minlength=bins)
    filled = counts > 0
    centres = 0.5 * (edges[:-1] + edges[1:])[filled]
    means = sums[filled] / counts[filled]
    if centres.size < 4:
        raise NoEdge("too few distinct positions to fit an edge")
    # Smooth before differentiating, over about 1/80 of the row: noise
    # has steep slopes too. Only the guess is smoothed, not the fit.
    width = max(1.0, centres.size / 80)
    radius = int(math.ceil(3 * width))
    taps = np.arange(-radius, radius + 1)
    kernel = np.exp(-0.5 * (taps / width) ** 2)
    kernel /= kernel.sum()
    padded = np.pad(means, radius, mode="edge")
    smooth = np.convolve(padded, kernel, mode="valid")
    slope = np.gradient(smooth, centres)
    first, last = 0, centres.size - 1
    if start_mm is not None:
        at = int(np.argmin(np.abs(centres - start_mm)))
    elif near is None:
        at = int(np.argmax(np.abs(slope)))
    else:
        size = np.abs(slope)
        peaks = np.flatnonzero(
            (size >= NEAR_CANDIDATE_SHARE * size.max())
            & (size >= np.roll(size, 1)) & (size >= np.roll(size, -1)))
        if peaks.size == 0:
            peaks = np.array([int(np.argmax(size))])
        which = int(np.argmin(np.abs(centres[peaks] - near)))
        at = int(peaks[which])
        if which > 0:
            first = (int(peaks[which - 1]) + at) // 2
        if which < peaks.size - 1:
            last = (at + int(peaks[which + 1])) // 2
    x0 = float(centres[at])

    # Plateaus: the outer third of each side of the edge.
    left = smooth[first: at + 1]
    right = smooth[at: last + 1]
    low = float(np.median(left[: max(1, left.size // 3)]))
    high = float(np.median(right[-max(1, right.size // 3):]))
    step = high - low
    # The binned profile's scatter, not one sample's: a row holds
    # thousands, and the edge only has to stand out of their average.
    noise = _noise(means)
    if abs(step) < MIN_STEP_TO_NOISE * noise:
        raise NoEdge(
            f"no edge: the step ({step:.3g} A) is within "
            f"{MIN_STEP_TO_NOISE:g}x the noise ({noise:.3g} A)")
    # Width: where the smoothed profile crosses 10 % and 90 % of the step.
    frac = (smooth - low) / step
    below = np.flatnonzero(frac[first: at + 1] <= 0.1)
    above = np.flatnonzero(frac[at: last + 1] >= 0.9)
    left_x = centres[first + below[-1]] if below.size else centres[first]
    right_x = centres[at + above[0]] if above.size else centres[last]
    width = max(right_x - left_x, 2 * (hi - lo) / bins)
    sigma = width / WIDTH_10_90_PER_SIGMA
    w_lo = lo if first == 0 else float(centres[first])
    w_hi = hi if last == centres.size - 1 else float(centres[last])
    return (np.array([x0, math.log(sigma), low, step, 0.0]), (w_lo, w_hi))


def _noise(y: np.ndarray) -> float:
    """Sample-to-sample scatter, robust to the edge itself."""
    d = np.diff(y)
    if d.size == 0:
        return 0.0
    return float(1.4826 * np.median(np.abs(d - np.median(d))) / _SQRT2)


def _result(x: np.ndarray, y: np.ndarray, p: np.ndarray) -> EdgeFit:
    x0, log_sigma, low, step, slope = (float(v) for v in p)
    sigma = math.exp(log_sigma)
    if not (x[0] <= x0 <= x[-1]):
        raise NoEdge(f"the fit put the edge at {x0:.4f} mm, outside the "
                     f"data ({x[0]:.4f} to {x[-1]:.4f} mm)")
    span = x[-1] - x[0]
    if sigma > span:
        raise NoEdge(f"the fitted edge ({sigma * 1000:.0f} um sigma) is "
                     "wider than the data")
    residual = y - _model(x, p)
    dof = max(1, x.size - p.size)
    variance = float(residual @ residual) / dof
    jac = _jacobian(x, p)
    try:
        covariance = np.linalg.inv(jac.T @ jac) * variance
        position_err = math.sqrt(max(covariance[0, 0], 0.0))
        sigma_err = sigma * math.sqrt(max(covariance[1, 1], 0.0))
    except np.linalg.LinAlgError:
        position_err = sigma_err = math.inf
    return EdgeFit(
        position_mm=x0, sigma_mm=sigma, low_a=low, step_a=step,
        slope_a_per_mm=slope, position_err_mm=position_err,
        sigma_err_mm=sigma_err, residual_a=math.sqrt(variance), n=int(x.size),
    )


# ---- rows ----


@dataclass(frozen=True)
class RowEdge:
    """One row's edge."""

    row: int
    #: +1 forward (A rising), -1 reverse, 0 measured standing still.
    direction: int
    b_mm: float
    fit: EdgeFit


@dataclass(frozen=True)
class EdgeShift:
    """The forward/reverse shift from edge positions: forward rows'
    edge minus reverse rows' edge, each row against the mean of its two
    neighbours, so an edge that leans or bows across rows cancels."""

    shift_mm: float
    #: Robust spread of the per-row values.
    spread_mm: float
    count: int

    def as_dict(self) -> dict[str, float | int]:
        return {"shift_um": self.shift_mm * 1000,
                "spread_um": self.spread_mm * 1000, "count": self.count}


def edge_shift(edges: list[RowEdge]) -> EdgeShift | None:
    """None if no row has a neighbour of the other direction on each
    side."""
    ordered = sorted(edges, key=lambda e: e.row)
    values = []
    for prev, row, nxt in zip(ordered, ordered[1:], ordered[2:], strict=False):
        if row.direction == 0 or not (
            prev.direction == nxt.direction == -row.direction
        ):
            continue
        if not (prev.row + 1 == row.row == nxt.row - 1):
            continue
        neighbours = 0.5 * (prev.fit.position_mm + nxt.fit.position_mm)
        values.append(row.direction * (row.fit.position_mm - neighbours))
    if not values:
        return None
    a = np.asarray(values)
    median = float(np.median(a))
    spread = float(1.4826 * np.median(np.abs(a - median)))
    return EdgeShift(median, spread, len(values))


#: Rows are refitted within this distance of the map's median edge, and
#: at least this many median widths.
REFIT_HALF_WINDOW_MM = 0.3
REFIT_WIDTHS = 6.0


def fit_rows(
    rows: list[tuple[int, int, float, np.ndarray, np.ndarray]],
    *,
    x_range: tuple[float, float] | None = None,
) -> tuple[list[RowEdge], dict[int, str]]:
    """Fit the same edge in every row: `(row, direction, b_mm, x, y)`.

    A first pass fits each row on its own; a second refits every row
    near the median of the first, so a row whose noise or a stray
    feature pulled it elsewhere finds the edge the others found.
    Returns the edges, and why each row that has none failed."""
    first: list[RowEdge] = []
    failed: dict[int, str] = {}
    for row, direction, b, x, y in rows:
        try:
            first.append(RowEdge(row, direction, b,
                                 fit_edge(x, y, x_range=x_range)))
        except NoEdge as exc:
            failed[row] = str(exc)
    if not first:
        return [], failed
    centre = float(np.median([e.fit.position_mm for e in first]))
    width = float(np.median([e.fit.width_mm for e in first]))
    half = max(REFIT_HALF_WINDOW_MM, REFIT_WIDTHS * width)
    window = (centre - half, centre + half)
    if x_range is not None:
        window = (max(window[0], min(x_range)), min(window[1], max(x_range)))
    edges: list[RowEdge] = []
    failed = {}
    for row, direction, b, x, y in rows:
        try:
            fit = fit_edge(x, y, x_range=window, start_mm=centre)
        except NoEdge as exc:
            failed[row] = str(exc)
            continue
        edges.append(RowEdge(row, direction, b, fit))
    return edges, failed
