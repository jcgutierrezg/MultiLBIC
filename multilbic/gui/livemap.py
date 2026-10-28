"""
A map built row by row as a run goes, and how far the run has got.

No Tk here. `LiveMap` takes each block of samples as the worker hands it
on (`RowDone`) and bins it the way the finished map does - the laser-off
baseline subtracted, mains removed per row - but without the serpentine
correction (D18): rows scanned in opposite directions sit a little
apart, by the shift the finished map then measures and removes.

`RunProgress` says how far a run has got and how long is left: the
plan's estimate until a few rows have finished, then the pace the rows
actually take, plus the baseline, warm-up and laser switch of each laser
still to come.
"""

from __future__ import annotations

import math

import numpy as np

from multilbic.run.rows import RowDone
from multilbic.run.session import LaserPlan
from multilbic.scan.binning import remove_mains
from multilbic.scan.mapping import BASELINE_ROW, WARMUP_ROW

#: The live display shows at most this many pixels a side; finer maps
#: are averaged down, so a redraw costs the same on the Pi whatever the
#: pixel size.
DISPLAY_MAX = 600
#: Rows to finish before their pace is trusted over the estimate.
MIN_ROWS_FOR_PACE = 3


class LiveMap:
    """Binned straight into a grid of at most `limit` pixels a side: a
    map with more pixels than that has blocks of them averaged, as it
    is arriving. The screen can't show more, a redraw then costs the
    same whatever the map, and a 30 mm map at 10 um doesn't hold 9
    million pixels in memory twice. The full map comes from the file
    at the end."""

    def __init__(self, plan: LaserPlan, mains_hz: float,
                 limit: int = DISPLAY_MAX):
        self.laser = plan.laser
        self.wavelength_nm = plan.wavelength_nm
        frame = plan.placement.frame
        request = plan.raster.request
        self.origin_a = frame.origin_ab_mm[0]
        self.width_mm = frame.width_mm
        self.height_mm = frame.height_mm
        self.pixel_mm = request.pixel_mm
        self.pitch_mm = request.pitch_mm
        self.mains_hz = mains_hz
        self.n_rows = len(plan.raster.rows)
        self.n_cols = max(1, math.ceil(self.width_mm / self.pixel_mm - 1e-9))
        #: Map rows and columns per grid pixel.
        self.row_block = max(1, math.ceil(self.n_rows / limit))
        self.col_block = max(1, math.ceil(self.n_cols / limit))
        shape = (math.ceil(self.n_rows / self.row_block),
                 math.ceil(self.n_cols / self.col_block))
        self.sums = np.zeros(shape)
        self.counts = np.zeros(shape, dtype=np.int64)
        self.offset_a = 0.0
        self.rows_done = 0
        self.baseline_done = False
        self.warmup_done = False
        #: How often the laser started again one range up.
        self.restarts = 0

    def add(self, block: RowDone) -> None:
        if not block.samples:
            return
        current = np.array([s.current_a for s in block.samples])
        if block.row == BASELINE_ROW:
            if self.rows_done or self.baseline_done:
                # A baseline after rows: the laser clipped and starts
                # again one range up (D26). Its earlier rows were on
                # another range: begin the map again.
                self.sums[:] = 0.0
                self.counts[:] = 0
                self.rows_done = 0
                self.restarts += 1
            self.offset_a = float(current.mean())
            self.baseline_done = True
            return
        if block.row == WARMUP_ROW:
            self.warmup_done = True
            return
        if not 0 <= block.row < self.n_rows:
            return
        # The SMU's own clock, as the finished map uses: host arrival
        # times come in ~100 ms bursts and would wreck the mains fit.
        t = np.array([s.device_ms for s in block.samples]) / 1000.0
        a = np.array([s.a_mm for s in block.samples])
        values = remove_mains(t, current, self.mains_hz) - self.offset_a
        cols = np.floor((a - self.origin_a) / self.pixel_mm).astype(int)
        inside = (cols >= 0) & (cols < self.n_cols)
        cols = cols[inside] // self.col_block
        row = block.row // self.row_block
        np.add.at(self.sums[row], cols, values[inside])
        np.add.at(self.counts[row], cols, 1)
        self.rows_done += 1

    def values(self) -> np.ndarray:
        """[row, column] in A, a pixel per block of the map's pixels;
        NaN where nothing has been measured."""
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(self.counts > 0,
                            self.sums / np.maximum(self.counts, 1), np.nan)


def shrink(values: np.ndarray, limit: int = DISPLAY_MAX) -> np.ndarray:
    """Block means (NaN ignored) to at most `limit` a side."""
    rows, cols = values.shape
    fr = max(1, math.ceil(rows / limit))
    fc = max(1, math.ceil(cols / limit))
    if fr == fc == 1:
        return values
    padded = np.full((math.ceil(rows / fr) * fr, math.ceil(cols / fc) * fc),
                     np.nan)
    padded[:rows, :cols] = values
    blocks = padded.reshape(padded.shape[0] // fr, fr,
                            padded.shape[1] // fc, fc)
    finite = np.isfinite(blocks)
    sums = np.where(finite, blocks, 0.0).sum(axis=(1, 3))
    counts = finite.sum(axis=(1, 3))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(counts > 0, sums / np.maximum(counts, 1), np.nan)


class RunProgress:
    def __init__(
        self,
        plans: tuple[LaserPlan, ...],
        estimate_s: float,
        started_s: float,
        overhead_per_laser_s: float,
    ):
        self.lasers = [p.laser for p in plans]
        self.rows_per_laser = {p.laser: len(p.raster.rows) for p in plans}
        self.rows_total = sum(self.rows_per_laser.values())
        self.estimate_s = estimate_s
        self.started_s = started_s
        self.overhead_s = overhead_per_laser_s
        self.rows_done = 0
        self.current: int | None = None
        self.row_in_laser = 0
        self._last_row_s: float | None = None
        self._row_times: list[float] = []

    def block(self, block: RowDone, now_s: float) -> None:
        if block.laser != self.current:
            self.current = block.laser
            self.row_in_laser = 0
            self._last_row_s = None
        if block.row < 0:
            if block.row == BASELINE_ROW and self.row_in_laser:
                # The laser starts again one range up (D26): its rows so
                # far will be scanned again.
                self.rows_done -= self.row_in_laser
                self.row_in_laser = 0
            # The baseline and warm-up: rows start timing after them.
            self._last_row_s = now_s
            return
        self.rows_done += 1
        self.row_in_laser = block.row + 1
        if self._last_row_s is not None and block.row > 0:
            self._row_times.append(now_s - self._last_row_s)
        self._last_row_s = now_s

    def remaining_s(self, now_s: float) -> float:
        elapsed = now_s - self.started_s
        if len(self._row_times) >= MIN_ROWS_FOR_PACE:
            pace = float(np.median(self._row_times))
            to_come = 0
            if self.current in self.lasers:
                to_come = len(self.lasers) - 1 - self.lasers.index(
                    self.current)
            return max(0.0, pace * (self.rows_total - self.rows_done)
                       + self.overhead_s * to_come)
        return max(0.0, self.estimate_s - elapsed)

    def fraction(self, now_s: float) -> float:
        elapsed = now_s - self.started_s
        total = elapsed + self.remaining_s(now_s)
        return 0.0 if total <= 0 else min(1.0, elapsed / total)
