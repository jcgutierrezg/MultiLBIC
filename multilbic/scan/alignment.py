"""
The serpentine self-calibration: how far forward rows sit from reverse
rows, measured from the data.

Anything that is constant in time - the `ok`'s latency, the stream's
smallest delay - puts every forward row a little one way and every
reverse row the other. Backlash does the same in position. Together
they show up as one shift `s` between neighbouring rows of opposite
direction: a feature at `p` appears at `p + s/2` in forward rows and
`p - s/2` in reverse ones. Correcting by half each way puts both back
on `p`, whatever the shift was made of.

How it is measured: each row's samples are put on a fine, common A grid
and smoothed; the derivative along A keeps the edges and drops any
offset or slow drift between rows; the cross-correlation of a forward
row with its reverse neighbour peaks at `s`, refined between grid
points with a parabola. The median over all pairs is the answer.
Neighbouring rows are one pitch apart in B, so this relies on features
that cross rows, such as fingers and cell edges along B. On a sample
with none, the correlation is weak and the shift is reported as not
found rather than guessed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

GRID_MM = 0.0005
SMOOTH_MM = 0.002
MAX_SHIFT_MM = 0.2
#: Below this normalised correlation peak a pair is not trusted.
MIN_QUALITY = 0.5


@dataclass(frozen=True)
class RowSamples:
    """One row's samples, positioned but not yet aligned."""

    direction: int
    a_mm: np.ndarray
    values: np.ndarray


@dataclass(frozen=True)
class Alignment:
    #: Forward-row position minus reverse-row position of one feature.
    shift_mm: float
    #: The median normalised correlation peak, 0..1.
    quality: float
    pairs: int
    found: bool

    def corrected(self, a_mm: np.ndarray, direction: int) -> np.ndarray:
        if not self.found:
            return a_mm
        return a_mm - direction * self.shift_mm / 2

    def as_dict(self) -> dict[str, float | int | bool]:
        return {
            "shift_um": self.shift_mm * 1000,
            "quality": self.quality,
            "pairs": self.pairs,
            "found": self.found,
        }


NOT_FOUND = Alignment(0.0, 0.0, 0, False)


def estimate_shift(
    rows: list[RowSamples],
    max_shift_mm: float = MAX_SHIFT_MM,
) -> Alignment:
    shifts, qualities = [], []
    for first, second in zip(rows, rows[1:], strict=False):
        if first.direction == second.direction:
            continue
        forward, reverse = (
            (first, second) if first.direction > 0 else (second, first)
        )
        found = _pair_shift(forward, reverse, max_shift_mm)
        if found is not None:
            shifts.append(found[0])
            qualities.append(found[1])
    if not shifts:
        return NOT_FOUND
    quality = float(np.median(qualities))
    good = [s for s, q in zip(shifts, qualities, strict=True) if q >= MIN_QUALITY]
    if not good:
        return Alignment(float(np.median(shifts)), quality, len(shifts), False)
    return Alignment(float(np.median(good)), quality, len(good), True)


def _profile(row: RowSamples, grid: np.ndarray) -> np.ndarray:
    order = np.argsort(row.a_mm, kind="stable")
    values = np.interp(grid, row.a_mm[order], row.values[order])
    radius = int(round(3 * SMOOTH_MM / GRID_MM))
    x = np.arange(-radius, radius + 1) * GRID_MM
    kernel = np.exp(-0.5 * (x / SMOOTH_MM) ** 2)
    smooth = np.convolve(values, kernel / kernel.sum(), mode="same")
    slope = np.gradient(smooth)
    # The kernel's edges are unreliable; flatten them.
    slope[:radius] = 0.0
    slope[-radius:] = 0.0
    return slope


def _pair_shift(
    forward: RowSamples,
    reverse: RowSamples,
    max_shift_mm: float,
) -> tuple[float, float] | None:
    lo = max(forward.a_mm.min(), reverse.a_mm.min())
    hi = min(forward.a_mm.max(), reverse.a_mm.max())
    if hi - lo < 4 * max_shift_mm:
        return None
    grid = np.arange(lo, hi, GRID_MM)
    f = _profile(forward, grid)
    g = _profile(reverse, grid)
    energy = np.sqrt(np.dot(f, f) * np.dot(g, g))
    if energy == 0:
        return None
    n = 1 << int(np.ceil(np.log2(2 * grid.size)))
    corr = np.fft.irfft(np.fft.rfft(f, n) * np.conj(np.fft.rfft(g, n)), n)
    max_lag = int(max_shift_mm / GRID_MM)
    lags = np.r_[np.arange(0, max_lag + 1), np.arange(-max_lag, 0)]
    values = corr[lags]
    best = int(np.argmax(values))
    peak = values[best]
    lag = float(lags[best])
    # Parabolic refinement between neighbouring lags.
    # Index -1 wraps to lag -1, as the circular correlation does.
    if abs(lags[best]) < max_lag:
        left = corr[lags[best] - 1]
        right = corr[lags[best] + 1]
        denominator = left - 2 * peak + right
        if denominator < 0:
            lag += 0.5 * (left - right) / denominator
    return lag * GRID_MM, float(peak / energy)
