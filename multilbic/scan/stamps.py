"""
Dating stream samples by their count, not by the miniSMU's stamps.

The miniSMU measures at a steady rate, but its stamps don't follow: they
run about 6 % slow for ~100 ms, then jump 5-8 ms to catch up, a
saw-tooth of about 6 ms (bench, 2026-11-03: 480 samples in every 599 ms
row at 800 Hz, the rate kept exactly, the stamps advancing 1.177 ms a
sample between jumps). A sample's position along a row comes from its
time, so the saw-tooth puts samples up to ~3 ms, 12 um at 4 mm/s, off
along the row, and leaves 2-3 empty 10 um pixels at each jump.

Since 0.6.35 a run file keeps every sample the stream gave, in order,
the ones between rows too (`GAP_ROW`), and says so in its header
(`stream: continuous`). Then each channel's samples can be dated by a
straight line of stamp against sample number, fitted over the whole
file, where the saw-tooth averages out. Where the line leaves the
stamps by more than `BREAK_MS` the stream must have lost samples or
restarted, and each stretch between such breaks gets its own line.
Older files, with holes between rows, keep their stamps.

**A stream that loses samples here and there keeps its stamps.** At
1000 Hz, 30 minutes of a real run lost about 3 % of its samples in
skips of up to 10 ms, none a break, and a line by count drifted from
-320 to +775 ms off the stamps (bench, 2026-11-06): its map's two
directions no longer met, and the alignment found no shift. So a line
is kept only where it stays within `FIT_MS` of the stamps, as a stream
with nothing lost does; a stretch it misses by more, with no step over
`BREAK_MS` to split it at, keeps its stamps, good to the saw-tooth's
few ms.
"""

from __future__ import annotations

import numpy as np

#: The saw-tooth spans about 6.5 ms around the line; a residual step
#: bigger than this is a break in the stream, not the saw-tooth.
BREAK_MS = 12.0
#: A loss-free stretch stays this close to its line (the bench's 800 Hz
#: stamps sat -1.7 to +4.7 ms off it, 2026-11-03). Further, and samples
#: were lost inside it: counting them would date it worse than this.
FIT_MS = 6.0
#: No stretch shorter than this is fitted on its own.
MIN_STRETCH = 50


def date_by_count(device_ms: np.ndarray, channel: np.ndarray) -> np.ndarray:
    """Each sample's time from its place in its channel's stream: the
    file's order is the stream's. Returns float milliseconds, on the
    device clock as the stamps are."""
    out = np.asarray(device_ms, dtype=float).copy()
    for ch in np.unique(channel):
        where = np.flatnonzero(channel == ch)
        out[where] = _line(out[where])
    return out


def _line(stamps: np.ndarray) -> np.ndarray:
    """Straight lines of stamp against sample number, one per stretch
    between breaks. A stretch too short to fit keeps its stamps."""
    n = stamps.size
    if n < MIN_STRETCH:
        return stamps.copy()
    index = np.arange(n, dtype=float)
    slope, offset = np.polyfit(index, stamps, 1)
    fitted = slope * index + offset
    if np.max(np.abs(stamps - fitted)) <= FIT_MS:
        return fitted
    # A break: split where the stamps step furthest from the stretch's
    # usual pace (a loss or a restart jumps the stamps; the saw-tooth's
    # jumps are smaller), and fit each side on its own. The usual pace
    # is the median step, which the break itself doesn't pull.
    steps = np.diff(stamps) - np.median(np.diff(stamps))
    at = int(np.argmax(np.abs(steps))) + 1
    if abs(steps[at - 1]) <= BREAK_MS:
        # Off the line with no break to split at: samples lost a few at
        # a time. Counting them would drift; the stamps don't.
        return stamps.copy()
    return np.concatenate([_line(stamps[:at]), _line(stamps[at:])])
