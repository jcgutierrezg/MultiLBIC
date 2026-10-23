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

**How much to smooth** depends on the laser's spot, which differs per
laser and with focus: no feature in a map is sharper than the spot, so
smoothing finer than it only correlates noise. With a 0.2 mm spot
(laser 2, bench 2026-10-23) a 2 µm smoothing found nothing, while
20-40 µm found the shift with confidence. So the smoothing is not
configured: several widths are tried, finest first, and the finest one
that gives a confident answer is used. A sharp spot keeps µm precision;
a broad one gets the smoothing it needs.
Neighbouring rows are one pitch apart in B, so this relies on features
that cross rows, such as fingers and cell edges along B. On a sample
with none, the correlation is weak and the shift is reported as not
found rather than guessed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

GRID_MM = 0.0005
#: Smoothing widths tried, finest first.
SMOOTH_SCALES_MM = (0.002, 0.005, 0.01, 0.02, 0.04, 0.08)
#: At 5 mm/s an 18.6 ms stamp lag alone is 0.19 mm of shift (bench).
MAX_SHIFT_MM = 0.4
#: Below this normalised correlation peak a pair is not trusted.
MIN_QUALITY = 0.5
#: A shift counts as found only if at least this share of the row
#: pairs, and at least `MIN_PAIRS` of them, are trusted. One lucky pair
#: among noise is not a measurement (bench, 2026-10-23).
MIN_TRUSTED_SHARE = 0.5
MIN_PAIRS = 3
#: And the trusted pairs must agree: their robust spread may be at most
#: the smoothing width plus this. On the bench they agreed within
#: 19-38 µm; rows of pure noise scatter across the whole search range
#: (150-400 µm in the tests).
SPREAD_ALLOWANCE_MM = 0.02


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
    #: The smoothing the answer was found with.
    smooth_mm: float = 0.0

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
            "smooth_um": self.smooth_mm * 1000,
        }


NOT_FOUND = Alignment(0.0, 0.0, 0, False)


def estimate_shift(
    rows: list[RowSamples],
    max_shift_mm: float = MAX_SHIFT_MM,
    smooth_mm: float | None = None,
) -> Alignment:
    """The shift, at `smooth_mm` if given, otherwise at the finest
    smoothing that finds it with confidence (`SMOOTH_SCALES_MM`). If
    none does, the most confident attempt, marked not found."""
    if smooth_mm is not None:
        return _at_scale(rows, max_shift_mm, smooth_mm)
    best = NOT_FOUND
    for scale in SMOOTH_SCALES_MM:
        attempt = _at_scale(rows, max_shift_mm, scale)
        if attempt.found:
            return attempt
        if attempt.quality > best.quality:
            best = attempt
    return best


def _at_scale(
    rows: list[RowSamples],
    max_shift_mm: float,
    smooth_mm: float,
) -> Alignment:
    shifts, qualities = [], []
    for first, second in zip(rows, rows[1:], strict=False):
        if first.direction == second.direction:
            continue
        forward, reverse = (
            (first, second) if first.direction > 0 else (second, first)
        )
        found = _pair_shift(forward, reverse, max_shift_mm, smooth_mm)
        if found is not None:
            shifts.append(found[0])
            qualities.append(found[1])
    if not shifts:
        return NOT_FOUND
    quality = float(np.median(qualities))
    good = [s for s, q in zip(shifts, qualities, strict=True) if q >= MIN_QUALITY]
    enough = max(MIN_PAIRS, MIN_TRUSTED_SHARE * len(shifts))
    if len(good) < enough or _spread(good) > smooth_mm + SPREAD_ALLOWANCE_MM:
        return Alignment(
            float(np.median(shifts)), quality, len(shifts), False, smooth_mm
        )
    return Alignment(
        float(np.median(good)), quality, len(good), True, smooth_mm
    )


def _spread(values: list[float]) -> float:
    """Robust standard deviation (scaled median absolute deviation)."""
    a = np.asarray(values)
    return float(1.4826 * np.median(np.abs(a - np.median(a))))


def _profile(
    row: RowSamples, grid: np.ndarray, smooth_mm: float
) -> np.ndarray:
    order = np.argsort(row.a_mm, kind="stable")
    values = np.interp(grid, row.a_mm[order], row.values[order])
    radius = int(round(3 * smooth_mm / GRID_MM))
    x = np.arange(-radius, radius + 1) * GRID_MM
    kernel = np.exp(-0.5 * (x / smooth_mm) ** 2)
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
    smooth_mm: float,
) -> tuple[float, float] | None:
    lo = max(forward.a_mm.min(), reverse.a_mm.min())
    hi = min(forward.a_mm.max(), reverse.a_mm.max())
    # Rows shorter than four times the search would mostly correlate
    # their own ends: search less far on them instead.
    max_shift_mm = min(max_shift_mm, (hi - lo) / 4)
    radius_mm = 3 * smooth_mm
    if hi - lo < 4 * radius_mm + 0.1:
        return None
    grid = np.arange(lo, hi, GRID_MM)
    f = _profile(forward, grid, smooth_mm)
    g = _profile(reverse, grid, smooth_mm)
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
