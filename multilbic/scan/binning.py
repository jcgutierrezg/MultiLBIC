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
  harmonics, subtracted. A row lasts tens of cycles, so a map feature
  barely projects onto them.
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
    return y - design[:, 1:] @ coefficients[1:]


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
