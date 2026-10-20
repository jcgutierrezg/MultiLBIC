"""
From a run's raw record to a map: the whole chain in one place.

Input is what a run records (`ScanData`): the row anchors and every raw
sample with both timestamps. Nothing computed during the run is reused,
so a run file can be re-mapped later with better calibration. The steps:

1. fit the clock map from all samples (`timing.fit_clock`);
2. the dark baseline (row -1) gives the offset and the noise floor;
3. each row's samples get host times, then A positions from that row's
   anchored motion; only samples taken while the row moved are kept;
4. mains is removed per row, the offset subtracted;
5. the serpentine shift is measured and corrected (`alignment`);
6. samples are binned into the pixel grid (`binning`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from multilbic.scan import alignment as align_mod
from multilbic.scan.alignment import Alignment, RowSamples
from multilbic.scan.binning import (
    NO_BASELINE,
    Baseline,
    Grid,
    baseline,
    bin_rows,
    remove_mains,
)
from multilbic.scan.geometry import SampleFrame
from multilbic.scan.timing import ClockMap, RowAnchor, fit_clock

BASELINE_ROW = -1


@dataclass(frozen=True)
class ScanData:
    """One laser's map as recorded."""

    frame: SampleFrame
    pixel_mm: float
    pitch_mm: float
    n_rows: int
    mains_hz: float
    anchors: tuple[RowAnchor, ...]
    #: Per sample: row index (-1 for the baseline), channel, device
    #: timestamp (ms), host arrival (s), current (A).
    row: np.ndarray
    channel: np.ndarray
    device_ms: np.ndarray
    host_s: np.ndarray
    current_a: np.ndarray
    laser: int = 0


@dataclass(frozen=True)
class MappedRow:
    index: int
    direction: int
    u_mm: np.ndarray
    values: np.ndarray
    device_ms: np.ndarray


@dataclass(frozen=True)
class MapResult:
    grid: Grid
    clock: ClockMap
    baseline: Baseline
    alignment: Alignment
    rows: list[MappedRow] = field(repr=False)


def build_map(
    data: ScanData,
    *,
    channel: int = 1,
    align: bool = True,
    mains: bool = True,
) -> MapResult:
    on_channel = data.channel == channel
    if not on_channel.any():
        raise ValueError(f"no samples on channel {channel}")
    clock = fit_clock(data.device_ms[on_channel], data.host_s[on_channel])

    is_base = on_channel & (data.row == BASELINE_ROW)
    if is_base.any():
        base = baseline(
            data.device_ms[is_base] / 1000.0,
            data.current_a[is_base],
            data.mains_hz,
        )
    else:
        base = NO_BASELINE

    positioned: list[tuple[RowAnchor, np.ndarray, np.ndarray, np.ndarray]] = []
    for anchor in data.anchors:
        mine = on_channel & (data.row == anchor.index)
        device_ms = data.device_ms[mine]
        values = data.current_a[mine]
        motion = anchor.motion()
        host = clock.to_host(device_ms)
        moving = (host >= motion.start_s) & (host <= motion.end_s)
        device_ms, values = device_ms[moving], values[moving]
        if mains and values.size:
            values = remove_mains(device_ms / 1000.0, values, data.mains_hz)
        values = values - base.offset_a
        positioned.append((anchor, motion.a_at(host[moving]), values, device_ms))

    if align:
        alignment = align_mod.estimate_shift(
            [
                RowSamples(anchor.motion().direction, a, v)
                for anchor, a, v, _ in positioned
                if a.size
            ]
        )
    else:
        alignment = align_mod.NOT_FOUND

    rows = []
    for anchor, a, values, device_ms in positioned:
        direction = anchor.motion().direction
        a = alignment.corrected(a, direction)
        u = a - data.frame.origin_ab_mm[0]
        rows.append(MappedRow(anchor.index, direction, u, values, device_ms))

    grid = bin_rows(
        [(r.index, r.u_mm, r.values) for r in rows],
        data.n_rows,
        data.frame.width_mm,
        data.pixel_mm,
        data.pitch_mm,
    )
    return MapResult(grid, clock, base, alignment, rows)
