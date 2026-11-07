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
5. the serpentine shift is measured and corrected (`alignment`), which
   puts each sample where the stage really was; half the known A
   backlash is then added, to match positions read after moving up as
   corner calibration reads them (`ab_backlash_mm`, machine.toml);
6. samples are binned into the pixel grid (`binning`).
"""

from __future__ import annotations

from collections.abc import Collection
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
from multilbic.scan.timing import (
    BENCH_ROW_REPLY_S,
    ClockMap,
    RowAnchor,
    fit_clock,
    settle_late_replies,
)

BASELINE_ROW = -1
#: Samples taken with the laser on and the stage still, before the first
#: row: how the laser's output settles after switching on. Kept in the
#: file, never mapped.
WARMUP_ROW = -2
#: The stream between the blocks above: before the baseline, while the
#: laser switches on, and through each turnaround between rows. Kept so
#: every sample the stream gave is in the file in order, which lets them
#: be dated by their count (`scan.stamps`); never mapped. No position.
GAP_ROW = -3


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
    #: From machine.toml when the run was made.
    ab_backlash_mm: float = 0.0
    #: Marlin's on-time delay from a row's `G1` to its `M400`'s ok,
    #: beyond the move (`[ab] row_reply_ms`; `settle_late_replies`).
    row_reply_s: float = BENCH_ROW_REPLY_S


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
    #: The late rows (their indices) placed from their reply rather than
    #: their send: with the alignment, what a saved alignment keeps
    #: (`store/alignfile`) so the map can be built again without
    #: searching for either.
    late_from_reply: tuple[int, ...] = ()


def build_map(
    data: ScanData,
    *,
    channel: int = 1,
    align: bool = True,
    mains: bool = True,
    alignment: Alignment | None = None,
    late_from_reply: Collection[int] | None = None,
) -> MapResult:
    """The map from `data`. Given an `alignment`, it is used as it is
    instead of being searched for (`align` is then ignored); given
    `late_from_reply`, those late rows are placed from their reply and
    the other late rows from their send, without comparing each with its
    neighbours. Both come from a saved alignment (`store/alignfile`):
    with them a big map builds in a fraction of the time."""
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

    def position(anchor: RowAnchor) -> Positioned:
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
        return anchor, motion.a_at(host[moving]), values, device_ms

    settled = settle_late_replies(data.anchors, data.row_reply_s)
    positioned = [position(anchor) for anchor in settled]
    # A late reply is mostly the reply alone being late, but sometimes
    # the move started late too (single rows, bench 2026-11-05): each
    # late row keeps the placement its neighbours agree with.
    from_reply: list[int] = []
    for k, (raw, new) in enumerate(zip(data.anchors, settled, strict=True)):
        if new.end_s == raw.end_s:
            continue
        if late_from_reply is not None:
            if raw.index in late_from_reply:
                positioned[k] = position(raw)
                from_reply.append(raw.index)
            continue
        by_reply = position(raw)
        positioned[k] = _agreeing(k, positioned, by_reply, settled,
                                  data.anchors)
        if positioned[k] is by_reply:
            from_reply.append(raw.index)

    if alignment is None:
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
        if alignment.found:
            a = a + data.ab_backlash_mm / 2
        u = a - data.frame.origin_ab_mm[0]
        rows.append(MappedRow(anchor.index, direction, u, values, device_ms))

    grid = bin_rows(
        [(r.index, r.u_mm, r.values) for r in rows],
        data.n_rows,
        data.frame.width_mm,
        data.pixel_mm,
        data.pitch_mm,
    )
    return MapResult(grid, clock, base, alignment, rows, tuple(from_reply))


Positioned = tuple[RowAnchor, np.ndarray, np.ndarray, np.ndarray]
#: A late row is compared with the on-time rows of its own direction this
#: many rows either side, smoothed this much (the alignment's scale for
#: a 50-100 um spot).
NEIGHBOUR_ROWS = 4
NEIGHBOUR_SMOOTH_MM = 0.02


def _agreeing(
    k: int,
    positioned: list[Positioned],
    from_reply: Positioned,
    settled: tuple[RowAnchor, ...],
    raw: tuple[RowAnchor, ...],
) -> Positioned:
    """Row `k` placed from its send (`positioned[k]`) or from its late
    reply (`from_reply`): whichever lines up better with the on-time
    rows near it that run the same way. With none of those, or nothing
    to line up (no feature crossing the rows), the send stays: a reply
    late for a stretch of rows was the reply alone."""
    from_send = positioned[k]
    direction = from_send[0].motion().direction
    neighbours = [
        positioned[j] for j in range(max(0, k - NEIGHBOUR_ROWS),
                                     min(len(positioned), k + NEIGHBOUR_ROWS + 1))
        if j != k and settled[j].end_s == raw[j].end_s
        and positioned[j][0].motion().direction == direction
        and positioned[j][1].size
    ]
    if not neighbours or not from_send[1].size or not from_reply[1].size:
        return from_send

    def misfit(candidate: Positioned) -> float | None:
        row = RowSamples(direction, candidate[1], candidate[2])
        shifts = []
        for n in neighbours:
            found = align_mod._pair_shift(
                row, RowSamples(direction, n[1], n[2]),
                align_mod.MAX_SHIFT_MM, NEIGHBOUR_SMOOTH_MM)
            if found is not None and found[1] >= align_mod.MIN_QUALITY:
                shifts.append(found[0])
        return abs(float(np.median(shifts))) if shifts else None

    send, reply = misfit(from_send), misfit(from_reply)
    if send is None or reply is None or send <= reply:
        return from_send
    return from_reply
