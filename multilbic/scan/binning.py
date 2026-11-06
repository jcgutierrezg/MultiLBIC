"""
Raw samples to a pixel grid, and the cleaning done on the way.

* **Dark baseline.** Each laser's map starts with a few seconds of
  streaming with the laser off and the stage still. Its mean is the
  offset subtracted from every sample, and its spread (after mains
  removal) is the noise floor the map has to clear.
* **Mains.** On open leads 89 % of the noise is 50 Hz and its
  harmonics (bench). Pixels along a row are a few milliseconds long, too
  short to average over whole 20 ms cycles, so mains is removed per row
  instead: a least-squares fit of sines at the mains frequency and its
  harmonics, subtracted.
  Fitted over the whole row, a big feature projects onto the sines:
  about 1 % of a step over 30 cycles, which on a cell's 1 mA edge is
  10 uA of 50 Hz put *into* the row, against tens of nA of mains
  (bench, 2026-11-05). That ripple repeats from row to row, so the
  serpentine alignment locked onto it, one mains cycle (80 um at
  4 mm/s) off. So the sines are also fitted where the row is flat
  only: each sample's level is the mean over one whole mains cycle
  around it, which holds no mains at all; where that level changes by
  more than twice the spread of what is left, the sample is not used,
  and the rest, mains and noise, is fitted. That fit is blind to
  features shorter than a cycle, which the whole row's fit averages
  out. A feature leaking into a fit only adds to it, and the mains is
  the same in both: the fit off the features is subtracted, unless it
  is more than twice the whole row's.
* **Slow drift** (0.2-0.7 Hz, the larger part with a cell connected) is
  not removed here. How to separate it from the signal is decision D8,
  set aside for now; the per-row cleaning is the place it would go.

The grid has one pixel row per scan row and `pixel_mm` columns along A.
Each pixel is the mean of the samples whose position falls in it;
pixels with none are NaN.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

MAINS_HARMONICS = 3


@dataclass(frozen=True)
class Baseline:
    offset_a: float
    noise_a: float
    samples: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "offset_a": self.offset_a,
            "noise_a": self.noise_a,
            "samples": self.samples,
        }


NO_BASELINE = Baseline(0.0, float("nan"), 0)


def remove_mains(
    t_s: np.ndarray,
    values: np.ndarray,
    mains_hz: float,
    harmonics: int = MAINS_HARMONICS,
) -> np.ndarray:
    """`values` with the best-fitting mains sines taken out. The mean
    is kept. Too few samples to fit, and the values come back as they
    were."""
    t = np.asarray(t_s, dtype=float)
    y = np.asarray(values, dtype=float)
    columns = [np.ones_like(t)]
    for k in range(1, harmonics + 1):
        w = 2 * math.pi * k * mains_hz * (t - t.mean())
        columns += [np.sin(w), np.cos(w)]
    if y.size < 4 * len(columns):
        return y.copy()
    design = np.column_stack(columns)
    coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
    residual, flat = _off_features(t, y, 1.0 / mains_hz)
    if flat.sum() >= 4 * len(columns) and np.ptp(t[flat]) >= 2.0 / mains_hz:
        off_features, *_ = np.linalg.lstsq(
            design[flat], residual[flat], rcond=None
        )
        # The fit off the features, unless it is more than twice the
        # whole row's: then features shorter than a cycle leaked into it.
        if np.sum(off_features[1:] ** 2) <= 4 * np.sum(coefficients[1:] ** 2):
            coefficients = off_features
    return y - design[:, 1:] @ coefficients[1:]


def _off_features(
    t: np.ndarray, y: np.ndarray, period_s: float
) -> tuple[np.ndarray, np.ndarray]:
    """Each sample minus its level, the mean over one mains period
    around it (which holds no mains), and where the row is flat enough
    for that difference to be mains and noise only."""
    order = np.argsort(t, kind="stable")
    ts, ys = t[order], y[order]
    # The running integral, so a mean over any span is a difference.
    integral = np.concatenate(
        ([0.0], np.cumsum(np.diff(ts) * (ys[1:] + ys[:-1]) / 2))
    )

    def mean_over(start: np.ndarray, end: np.ndarray) -> np.ndarray:
        return (np.interp(end, ts, integral)
                - np.interp(start, ts, integral)) / (end - start)

    half = period_s / 2
    level = mean_over(ts - half, ts + half)
    change = mean_over(ts, ts + period_s) - mean_over(ts - period_s, ts)
    residual = ys - level
    # Only where both spans lie inside the row.
    inside = (ts >= ts[0] + period_s) & (ts <= ts[-1] - period_s)
    flat = np.zeros(ts.size, dtype=bool)
    if inside.any():
        r = residual[inside]
        spread = 1.4826 * float(np.median(np.abs(r - np.median(r))))
        flat = inside & (np.abs(change) <= 2 * spread)
    out_residual = np.empty_like(residual)
    out_flat = np.empty_like(flat)
    out_residual[order] = residual
    out_flat[order] = flat
    return out_residual, out_flat


def baseline(
    t_s: np.ndarray,
    values: np.ndarray,
    mains_hz: float,
) -> Baseline:
    y = np.asarray(values, dtype=float)
    if y.size == 0:
        return NO_BASELINE
    clean = remove_mains(t_s, y, mains_hz)
    noise = float(np.std(clean)) if y.size > 1 else float("nan")
    return Baseline(float(np.mean(y)), noise, int(y.size))


@dataclass(frozen=True)
class Grid:
    """values[row, column]; column `j` covers
    `u` in [j * pixel, (j + 1) * pixel)."""

    values: np.ndarray
    counts: np.ndarray
    pixel_mm: float
    pitch_mm: float

    @property
    def u_centres(self) -> np.ndarray:
        return (np.arange(self.values.shape[1]) + 0.5) * self.pixel_mm

    @property
    def v_centres(self) -> np.ndarray:
        return (np.arange(self.values.shape[0]) + 0.5) * self.pitch_mm


def bin_rows(
    rows: list[tuple[int, np.ndarray, np.ndarray]],
    n_rows: int,
    width_mm: float,
    pixel_mm: float,
    pitch_mm: float,
) -> Grid:
    """`rows` is (row index, u positions, values) per row."""
    n_cols = max(1, math.ceil(width_mm / pixel_mm - 1e-9))
    sums = np.zeros((n_rows, n_cols))
    counts = np.zeros((n_rows, n_cols), dtype=int)
    for index, u, values in rows:
        if not 0 <= index < n_rows:
            continue
        cols = np.floor(np.asarray(u) / pixel_mm).astype(int)
        inside = (cols >= 0) & (cols < n_cols)
        np.add.at(sums[index], cols[inside], np.asarray(values)[inside])
        np.add.at(counts[index], cols[inside], 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        values = np.where(counts > 0, sums / np.maximum(counts, 1), np.nan)
    return Grid(values, counts, pixel_mm, pitch_mm)
