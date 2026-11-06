"""
Step-and-measure: positions with no timing in them.

A continuous row puts each sample where the stage was when it was
measured, which rests on the clock map, the row's anchor and the motion
model. Step-and-measure doesn't: the stage moves to a point, stops,
waits for it to settle, and the SMU is averaged there while nothing
moves. Where the current changes is then where the stage really was, to
the stage's own accuracy. Comparing an edge found this way with the same
edge in continuous rows gives the sync error (Phase 6, step 2), and
`multilbic.run.sync` makes that comparison in one session.

Each row is approached from below on A and B (`run.motion.approach`),
and then every point is reached moving up along A, so the stage sits on
the same side of its backlash throughout, as in a forward row. Points
are `step_mm` apart from the frame's left edge to its right; rows sit
where a raster of the same frame and pitch puts them, so the two can be
compared row by row.

The SMU streams all along, as in a scan. Only samples inside each
point's dwell are kept: they are written with `direction` 0 and the
point's commanded position as `a_mm`, `b_mm`. The dwell is rounded up to
whole mains periods, so averaging a point removes mains pickup. The
file is a run file like any other (`multilbic.store.runfile`), with
`mode: steps` in its header and no row anchors.

However it ends, it ends as `scan_laser` does: motion stopped unless it
completed, laser off, SMU output off, status in the file.
"""

from __future__ import annotations

import datetime
import math
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from multilbic.clock import Clock
from multilbic.config.machine import MachineConfig
from multilbic.run.motion import AB_TRAVEL_FEED_MM_S, RunStopped, approach
from multilbic.run.rows import (
    DEFAULT_BASELINE_S,
    DEFAULT_CURRENT_RANGE_A,
    DEFAULT_WARMUP_S,
    RangeClipped,
    RowDone,
    ScanDevices,
    StreamFault,
    _check_range,
    _Collector,
    _sample_row,
    _shut_down,
    current_limit_for,
)
from multilbic.scan.geometry import SampleFrame
from multilbic.scan.mapping import BASELINE_ROW, WARMUP_ROW
from multilbic.scan.raster import RasterError
from multilbic.scan.timing import FIRST_MOVE_DELAY_S, Trapezoid, axis_accel
from multilbic.store.runfile import RunWriter, SampleRow
from multilbic.version import app_version

#: The stream's rate while stepping. Nothing moves while samples are
#: kept, so the rate only sets how many are averaged per point.
STEP_STREAM_HZ = 500.0
DEFAULT_SETTLE_S = 0.2
DEFAULT_DWELL_S = 0.2
#: A point with fewer samples than this share of what its dwell should
#: hold is a fault, as a short row is in a scan.
MIN_POINT_SAMPLE_SHARE = 0.5
#: Per point beyond the move, settle and dwell, for the estimate: the
#: `M400` round trip and the host's own work.
POINT_OVERHEAD_S = 0.03
#: The most points a step run may have: at about half a second each,
#: 4000 is over half an hour. A step run is for a small patch.
MAX_POINTS = 4000


@dataclass(frozen=True)
class StepRequest:
    #: The patch: points span its width, rows its height.
    frame: SampleFrame
    #: Distance between points along A.
    step_mm: float
    #: Distance between rows along B.
    pitch_mm: float
    settle_s: float = DEFAULT_SETTLE_S
    dwell_s: float = DEFAULT_DWELL_S


@dataclass(frozen=True)
class StepRow:
    index: int
    b_mm: float
    #: The points, in the order visited: A rising.
    a_mm: tuple[float, ...]


@dataclass(frozen=True)
class StepPlan:
    request: StepRequest
    rows: tuple[StepRow, ...]
    stream_hz: float
    #: The dwell actually used: whole mains periods.
    dwell_s: float
    estimate_s: float

    @property
    def points(self) -> int:
        return sum(len(row.a_mm) for row in self.rows)


def plan_steps(request: StepRequest, machine: MachineConfig) -> StepPlan:
    r = request
    ab = machine.ab
    if r.step_mm < ab.microstep_mm:
        raise RasterError(f"step {r.step_mm} mm is below one microstep "
                          f"({ab.microstep_mm} mm)")
    if r.pitch_mm < ab.microstep_mm:
        raise RasterError(f"row pitch {r.pitch_mm} mm is below one "
                          f"microstep ({ab.microstep_mm} mm)")
    if r.settle_s < 0 or r.dwell_s <= 0:
        raise RasterError("settle must be >= 0 s and dwell > 0 s")
    period = 1.0 / machine.mains_hz
    dwell = math.ceil(r.dwell_s / period - 1e-9) * period

    n_points = int(math.floor(r.frame.width_mm / r.step_mm + 1e-9)) + 1
    n_rows = max(1, round(r.frame.height_mm / r.pitch_mm))
    if n_points * n_rows > MAX_POINTS:
        raise RasterError(
            f"{n_points} x {n_rows} = {n_points * n_rows} points is more "
            f"than {MAX_POINTS}: use a smaller patch, a larger step or "
            "fewer rows")
    rows = []
    for k in range(n_rows):
        _, b = r.frame.to_ab(0.0, (k + 0.5) * r.pitch_mm)
        a = tuple(r.frame.to_ab(i * r.step_mm, 0.0)[0]
                  for i in range(n_points))
        rows.append(StepRow(k, b, a))
    for row in rows:
        for axis, value in (("A", row.a_mm[0]), ("A", row.a_mm[-1]),
                            ("B", row.b_mm)):
            if not ab.safe_min_mm <= value <= ab.safe_max_mm:
                raise RasterError(
                    f"row {row.index} needs {axis}{value:.4f}, outside the "
                    f"safe range {ab.safe_min_mm}..{ab.safe_max_mm} mm")

    accel = axis_accel(ab.max_accel_mm_s2)
    per_point = (FIRST_MOVE_DELAY_S
                 + Trapezoid(r.step_mm, AB_TRAVEL_FEED_MM_S, accel).duration_s
                 + r.settle_s + dwell + POINT_OVERHEAD_S)
    # Each row also has its approach (two moves) and the stream's catch-up.
    per_row = 2 * FIRST_MOVE_DELAY_S + 0.5
    estimate = n_rows * (per_row + n_points * per_point)
    return StepPlan(r, tuple(rows), STEP_STREAM_HZ, dwell, estimate)


def step_laser(
    devices: ScanDevices,
    machine: MachineConfig,
    plan: StepPlan,
    laser: int,
    writer: RunWriter,
    clock: Clock,
    *,
    baseline_s: float = DEFAULT_BASELINE_S,
    warmup_s: float = DEFAULT_WARMUP_S,
    bias_v: float = 0.0,
    current_range_a: float | None = DEFAULT_CURRENT_RANGE_A,
    stop: threading.Event | None = None,
    say: Callable[[str], None] = lambda text: None,
    on_row: Callable[[RowDone], None] | None = None,
) -> dict[str, Any]:
    """Step-and-measure one laser over `plan`. Returns the trailer
    written to the file; raises `RunStopped` or the fault that ended it,
    with the file finished either way (as `scan_laser`)."""
    marlin, board, smu = devices.marlin, devices.laser, devices.smu
    rows = plan.rows
    settle = plan.request.settle_s
    stop = stop or threading.Event()
    status = "incomplete"
    trailer: dict[str, Any] = {}
    collector = _Collector(smu, clock)

    def check_stop() -> None:
        if stop.is_set():
            raise RunStopped("stopped by the operator")

    def written(row: int, samples: list[SampleRow]) -> None:
        if on_row is None:
            return
        try:
            on_row(RowDone(laser, row, len(rows), tuple(samples)))
        except Exception as exc:
            say(f"row display failed: {type(exc).__name__}: {exc}")

    def wait(seconds: float) -> None:
        end = clock.now() + seconds
        while (left := end - clock.now()) > 0:
            check_stop()
            clock.sleep(min(0.5, left))

    try:
        first = rows[0]
        approach(marlin, machine, a=first.a_mm[0], b=first.b_mm, stop=stop)

        board.off()
        smu.prepare(bias_v=bias_v, current_range_a=current_range_a,
                    current_limit_a=current_limit_for(current_range_a))
        smu.output_on()
        smu.stream.start(channels=(1,), rate_hz=plan.stream_hz)

        say(f"baseline: {baseline_s:g} s with the laser off")
        t0 = clock.now()
        clock.sleep(baseline_s)
        t1 = clock.now()
        collector.wait_past(t1)
        stage = marlin.position()
        baseline = collector.take(t0, t1)
        block = [_sample_row(s, BASELINE_ROW, 0, stage["A"], stage["B"])
                 for s, _ in baseline]
        writer.write_samples(block)
        written(BASELINE_ROW, block)
        _check_range(baseline, current_range_a, "the baseline")

        check_stop()
        say(f"laser {laser} on")
        board.select(laser)
        if warmup_s > 0:
            say(f"warm-up: {warmup_s:g} s with laser {laser} on")
            w0 = clock.now()
            wait(warmup_s)
            w1 = clock.now()
            collector.wait_past(w1)
            block = [_sample_row(s, WARMUP_ROW, 0, stage["A"], stage["B"])
                     for s, _ in collector.take(w0, w1)]
            writer.write_samples(block)
            written(WARMUP_ROW, block)

        expected = plan.stream_hz * plan.dwell_s
        for row in rows:
            check_stop()
            approach(marlin, machine, a=row.a_mm[0], b=row.b_mm, stop=stop)
            windows: list[tuple[float, float, float]] = []
            for i, a in enumerate(row.a_mm):
                if i > 0:
                    marlin.move_to(feed_mm_s=AB_TRAVEL_FEED_MM_S, a=a)
                    marlin.wait_idle()
                check_stop()
                wait(settle)
                p0 = clock.now()
                wait(plan.dwell_s)
                windows.append((a, p0, clock.now()))
                collector.pull()
            if not collector.wait_past(windows[-1][2]):
                raise StreamFault(
                    f"row {row.index}: the stream stalled during the row")
            taken = collector.take(windows[0][1], windows[-1][2])
            _check_range(taken, current_range_a, f"row {row.index}")
            block = []
            counts = [0] * len(windows)
            point = 0
            for sample, host in taken:
                while point < len(windows) and host > windows[point][2]:
                    point += 1
                if point == len(windows):
                    break
                a, lo, _ = windows[point]
                if host >= lo:
                    counts[point] += 1
                    block.append(_sample_row(sample, row.index, 0, a,
                                             row.b_mm))
            short = [i for i, n in enumerate(counts)
                     if n < MIN_POINT_SAMPLE_SHARE * expected]
            if short:
                raise StreamFault(
                    f"row {row.index}: {len(short)} point(s) with fewer than "
                    f"{MIN_POINT_SAMPLE_SHARE * expected:.0f} samples "
                    f"(the first at A{row.a_mm[short[0]]:.4f})")
            writer.write_samples(block)
            written(row.index, block)
            say(f"row {row.index + 1}/{len(rows)}: {len(windows)} points")
        status = "complete"
    except RunStopped:
        status = "stopped"
        raise
    except RangeClipped as exc:
        status = f"clipped: {exc}"
        raise
    except BaseException as exc:
        status = f"failed: {type(exc).__name__}: {exc}"
        raise
    finally:
        _shut_down(devices, moving=status != "complete", say=say)
        if collector.received:
            trailer["clock_map"] = collector.tracker.fit().as_dict()
        trailer["samples_received"] = collector.received
        writer.finish(status, trailer)
    return trailer


def step_header(
    machine: MachineConfig,
    plan: StepPlan,
    laser: int,
    *,
    sample: str,
    simulated: bool,
    firmware: dict[str, str | None],
    provenance: dict[str, Any],
    current_range_a: float | None = DEFAULT_CURRENT_RANGE_A,
    warmup_s: float = DEFAULT_WARMUP_S,
) -> dict[str, Any]:
    """The header of a step-and-measure run file. The frame, pixel and
    pitch keys are the same as a scan's, so the file reads the same."""
    r = plan.request
    return {
        "mode": "steps",
        "sample": sample,
        "simulated": simulated,
        "started": datetime.datetime.now(datetime.UTC).isoformat(
            timespec="seconds"),
        "app_version": app_version(),
        "provenance": provenance,
        "firmware": firmware,
        "laser": laser,
        "wavelength_nm": machine.laser(laser).wavelength_nm,
        "frame_origin_ab_mm": list(r.frame.origin_ab_mm),
        "frame_size_mm": [r.frame.width_mm, r.frame.height_mm],
        "pixel_mm": r.step_mm,
        "pitch_mm": r.pitch_mm,
        "n_rows": len(plan.rows),
        "points_per_row": len(plan.rows[0].a_mm),
        "settle_s": r.settle_s,
        "dwell_s": plan.dwell_s,
        "approach": "every point reached moving up along A",
        "stream_hz": plan.stream_hz,
        "mains_hz": machine.mains_hz,
        "warmup_s": warmup_s,
        "current_range_a": current_range_a,
        "current_limit_a": current_limit_for(current_range_a),
        "ab_backlash_mm": machine.geometry.ab_backlash_mm,
        "estimate_s": round(plan.estimate_s, 1),
    }
