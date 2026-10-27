"""
The row plan: which rows, in which order, at what speed and stream rate.

Each row is one move along A at constant B. It starts a run-up before
the sample's edge and ends a run-out after the other edge, so the
measured span is crossed at full speed: acceleration happens outside
it. The run-up is at least the acceleration distance plus a margin.

Rows sit at the centres of the map's pixel rows: row `k` is at
`v = (k + 0.5) * pitch`. Serpentine order (the default, D3) alternates
direction; the forward/reverse difference is what the alignment
measures. One-direction scanning returns A to the start between rows.

The stream rate follows from the requested pixel size (D2): enough
samples per pixel at the chosen speed, capped at what the host has been
seen to keep up with.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from multilbic.config.machine import MachineConfig
from multilbic.scan.geometry import SampleFrame
from multilbic.scan.timing import FIRST_MOVE_DELAY_S, Trapezoid, axis_accel

#: The highest stream rate a scan asks for. The instrument tops out
#: near 1400 Hz and the Pi's bulk reader kept up at about 1190 Hz
#: (bench, 2026-10-19); 1000 leaves a margin.
MAX_STREAM_HZ = 1000.0
#: The per-row cleaning fits sines at 50, 100 and 150 Hz, and room light
#: flickers at 100 Hz (8 % of the noise with the lights on, bench
#: 2026-10-20). Below about 400 Hz the 100 Hz and 150 Hz sines sit at or
#: near half the sample rate, where they can't be told apart from each
#: other or fitted.
MIN_STREAM_HZ = 400.0
#: Run-up beyond the acceleration distance.
RUN_UP_MARGIN_MM = 0.05
MIN_RUN_UP_MM = 0.1
#: Per row, beyond the moves, for the estimate: the host's round trips,
#: waiting for the stream's next burst (about every 100 ms) to pass the
#: row's end, and writing the row. Bench, 2026-10-23 and 26: rows cycled
#: in 2.62 s where the moves alone model 2.50 s (2 mm rows at 1 mm/s).
ROW_OVERHEAD_S = 0.13
#: How fast the stage moves between rows (B steps, one-direction
#: returns). Nothing is measured then, so vibration doesn't matter; 5
#: mm/s stays below the 6 mm/s that was noisy on B (D9).
TRAVEL_FEED_MM_S = 5.0


class RasterError(ValueError):
    pass


@dataclass(frozen=True)
class ScanRequest:
    frame: SampleFrame
    #: Pixel size along A, for the map. Positions are kept per sample.
    pixel_mm: float
    #: Distance between rows along B (the map's pixel height).
    pitch_mm: float
    speed_mm_s: float
    serpentine: bool = True
    samples_per_pixel: float = 2.0


@dataclass(frozen=True)
class Row:
    index: int
    b_mm: float
    #: Where the move starts and ends, run-up and run-out included.
    a_from_mm: float
    a_to_mm: float

    @property
    def forward(self) -> bool:
        return self.a_to_mm > self.a_from_mm


@dataclass(frozen=True)
class RasterPlan:
    request: ScanRequest
    rows: tuple[Row, ...]
    run_up_mm: float
    accel_mm_s2: float
    stream_hz: float
    #: Rough time for the rows, without homing, calibration or lasers.
    estimate_s: float

    @property
    def samples_per_pixel(self) -> float:
        r = self.request
        return self.stream_hz * r.pixel_mm / r.speed_mm_s


def plan_raster(request: ScanRequest, machine: MachineConfig) -> RasterPlan:
    ab = machine.ab
    r = request
    if r.speed_mm_s <= 0 or r.speed_mm_s > ab.max_feed_mm_s:
        raise RasterError(
            f"speed {r.speed_mm_s} mm/s is outside 0..{ab.max_feed_mm_s} "
            "mm/s (machine.toml [ab] max_feed_mm_s)"
        )
    if r.pitch_mm < ab.microstep_mm:
        raise RasterError(
            f"row pitch {r.pitch_mm} mm is below one microstep "
            f"({ab.microstep_mm} mm)"
        )
    if r.pixel_mm <= 0:
        raise RasterError("pixel size must be > 0")

    accel = axis_accel(ab.max_accel_mm_s2)
    run_up = max(
        MIN_RUN_UP_MM, r.speed_mm_s**2 / (2 * accel) + RUN_UP_MARGIN_MM
    )
    stream_hz = _stream_rate(r)

    n_rows = max(1, round(r.frame.height_mm / r.pitch_mm))
    a_lo, _ = r.frame.to_ab(0.0, 0.0)
    a_hi, _ = r.frame.to_ab(r.frame.width_mm, 0.0)
    rows = []
    for k in range(n_rows):
        _, b = r.frame.to_ab(0.0, (k + 0.5) * r.pitch_mm)
        forward = (k % 2 == 0) or not r.serpentine
        start, end = a_lo - run_up, a_hi + run_up
        rows.append(Row(k, b, start, end) if forward else Row(k, b, end, start))

    for row in rows:
        for axis, value in (
            ("A", row.a_from_mm), ("A", row.a_to_mm), ("B", row.b_mm)
        ):
            if not ab.safe_min_mm <= value <= ab.safe_max_mm:
                raise RasterError(
                    f"row {row.index} needs {axis}{value:.4f}, outside the "
                    f"safe range {ab.safe_min_mm}..{ab.safe_max_mm} mm"
                )

    estimate = _estimate(rows, r, accel)
    return RasterPlan(r, tuple(rows), run_up, accel, stream_hz, estimate)


def _stream_rate(r: ScanRequest) -> float:
    wanted = r.samples_per_pixel * r.speed_mm_s / r.pixel_mm
    rate = min(max(wanted, MIN_STREAM_HZ), MAX_STREAM_HZ)
    if rate * r.pixel_mm / r.speed_mm_s < 1.0:
        fastest = MAX_STREAM_HZ * r.pixel_mm
        raise RasterError(
            f"{r.pixel_mm * 1000:g} µm pixels at {r.speed_mm_s} mm/s need "
            f"more than {MAX_STREAM_HZ:g} samples/s: scan at "
            f"{fastest:.3g} mm/s or slower, or use larger pixels"
        )
    return float(math.ceil(rate))


def _estimate(rows: list[Row], r: ScanRequest, accel: float) -> float:
    total = 0.0
    previous: Row | None = None
    for row in rows:
        if previous is not None:
            step = Trapezoid(
                abs(row.b_mm - previous.b_mm), TRAVEL_FEED_MM_S, accel
            )
            total += FIRST_MOVE_DELAY_S + step.duration_s
            if not r.serpentine:
                back = Trapezoid(
                    abs(row.a_from_mm - previous.a_to_mm),
                    TRAVEL_FEED_MM_S,
                    accel,
                )
                total += back.duration_s
        move = Trapezoid(
            abs(row.a_to_mm - row.a_from_mm), r.speed_mm_s, accel
        )
        total += FIRST_MOVE_DELAY_S + move.duration_s + ROW_OVERHEAD_S
        previous = row
    return total
