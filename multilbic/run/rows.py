"""
One laser's map, row by row, written to a run file as it goes.

This is the part of a run that Phase 3 needs to make a map: position the
stage, record a dark baseline, light the laser, then for each row step B,
move along A at the scan speed, and anchor the row on the `M400` that
ends it. The SMU streams throughout; after each row the samples taken
while it moved are written out with its anchor.

Homing, calibration, XY placement and the loop over lasers are the
session's (`multilbic.run.session`). This module owns one laser's map
and how it ends:

* **Stop** is a `threading.Event`, checked before every row and after
  every wait. Whoever sets it also calls `Marlin.quickstop()`, so a row
  in progress stops at once; that row is not written, since its end is
  no longer where the motion model says.
* **Faults** end the map the same way: a device error from any driver,
  or the stream going wrong (stalled, a read error, or a row with less
  than half the samples it should have).
* **However it ends**: motion stopped unless it completed, laser off,
  stream stopped, SMU output off, and the file's status says `complete`,
  `stopped` or `failed: <why>`.
"""

from __future__ import annotations

import datetime
import threading
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any

import numpy as np

from multilbic.clock import Clock
from multilbic.config.machine import MachineConfig
from multilbic.hardware.laser import LaserBoard
from multilbic.hardware.marlin import Marlin
from multilbic.hardware.smu import PhotocurrentSmu, SmuError, StreamSample
from multilbic.run.motion import AB_TRAVEL_FEED_MM_S, approach
from multilbic.scan.mapping import BASELINE_ROW
from multilbic.scan.raster import TRAVEL_FEED_MM_S, RasterPlan
from multilbic.scan.timing import ClockTracker, RowAnchor
from multilbic.store.runfile import RunWriter, SampleRow

#: Samples this close outside a row's move are kept with it.
ROW_MARGIN_S = 0.02
#: How long to wait for the stream to catch up with the end of a row.
#: It arrives in bursts about every 100 ms.
CATCH_UP_S = 2.0
DEFAULT_BASELINE_S = 3.0
#: A row with fewer samples than this share of what the stream rate
#: promises is a fault. The real rate misses the requested one by up to
#: ~19 % (bench), so half is far outside normal.
MIN_ROW_SAMPLE_SHARE = 0.5
#: A fixed current range reads no further than its end; a sample this
#: close to it is taken as clipped.
SATURATION_SHARE = 0.98
#: The default range for scans: autoranging drops samples at every
#: range switch (bench, 2026-10-21). 25 uA had 2.1 nA RMS on the bench.
DEFAULT_CURRENT_RANGE_A = 25e-6


class RunStopped(Exception):
    """The operator asked to stop."""


class StreamFault(SmuError):
    """The SMU stream stopped delivering what it should."""


@dataclass
class ScanDevices:
    marlin: Marlin
    laser: LaserBoard
    smu: PhotocurrentSmu


class _Collector:
    """Samples drained from the stream, kept until a row claims them."""

    def __init__(self, smu: PhotocurrentSmu, clock: Clock):
        self._stream = smu.stream
        self._clock = clock
        self.tracker = ClockTracker()
        self._pending: list[StreamSample] = []
        self.received = 0

    def pull(self) -> None:
        error = self._stream.stats.read_error
        if error:
            raise StreamFault(f"stream read failed: {error}")
        new = self._stream.drain()
        if not new:
            return
        self.received += len(new)
        self.tracker.add(
            np.array([s.device_ms for s in new]),
            np.array([s.host_s for s in new]),
        )
        self._pending.extend(new)

    def wait_past(self, host_s: float) -> bool:
        """Wait until a sample taken after host time `host_s` is in."""
        deadline = self._clock.now() + CATCH_UP_S
        while True:
            self.pull()
            if self._pending:
                last = self.tracker.fit().to_host(self._pending[-1].device_ms)
                if float(last) >= host_s:
                    return True
            if self._clock.now() >= deadline:
                return False
            self._clock.sleep(0.01)

    def take(
        self, lo_s: float, hi_s: float
    ) -> list[tuple[StreamSample, float]]:
        """Samples taken in [lo_s, hi_s], with their mapped host times.
        Older ones are dropped; newer ones wait for the next row."""
        if not self._pending:
            return []
        host = self.tracker.fit().to_host(
            np.array([s.device_ms for s in self._pending])
        )
        taken, later = [], []
        for sample, h in zip(self._pending, host, strict=True):
            if h > hi_s:
                later.append(sample)
            elif h >= lo_s:
                taken.append((sample, float(h)))
        self._pending = later
        return taken


def scan_laser(
    devices: ScanDevices,
    machine: MachineConfig,
    plan: RasterPlan,
    laser: int,
    writer: RunWriter,
    clock: Clock,
    *,
    baseline_s: float = DEFAULT_BASELINE_S,
    bias_v: float = 0.0,
    current_range_a: float | None = DEFAULT_CURRENT_RANGE_A,
    stop: threading.Event | None = None,
    say: Callable[[str], None] = lambda text: None,
) -> dict[str, Any]:
    """Run one laser's map. Returns the trailer written to the file.
    Raises `RunStopped` if `stop` was set, or the fault that ended it;
    the file is finished either way."""
    marlin, board, smu = devices.marlin, devices.laser, devices.smu
    request = plan.request
    rows = plan.rows
    stop = stop or threading.Event()
    status = "incomplete"
    trailer: dict[str, Any] = {}
    collector = _Collector(smu, clock)

    def check_stop() -> None:
        if stop.is_set():
            raise RunStopped("stopped by the operator")

    try:
        first = rows[0]
        # A first, then B: both arrive moving up, so B's backlash is
        # taken up the way every later row step takes it (always +B).
        approach(marlin, machine, a=first.a_from_mm, b=first.b_mm)
        check_stop()

        board.off()
        smu.prepare(bias_v=bias_v, current_range_a=current_range_a)
        smu.output_on()
        smu.stream.start(channels=(1,), rate_hz=plan.stream_hz)

        say(f"baseline: {baseline_s:g} s with the laser off")
        t0 = clock.now()
        clock.sleep(baseline_s)
        t1 = clock.now()
        collector.wait_past(t1)
        stage = marlin.position()
        baseline = collector.take(t0, t1)
        writer.write_samples(
            [
                _sample_row(s, BASELINE_ROW, 0, stage["A"], stage["B"])
                for s, _ in baseline
            ]
        )
        _check_range(baseline, current_range_a, "the baseline")

        check_stop()
        say(f"laser {laser} on")
        board.select(laser)

        for row in rows:
            check_stop()
            if row.index > 0:
                if not request.serpentine:
                    marlin.move_to(
                        feed_mm_s=AB_TRAVEL_FEED_MM_S, a=row.a_from_mm
                    )
                marlin.move_to(feed_mm_s=TRAVEL_FEED_MM_S, b=row.b_mm)
                marlin.wait_idle()
                check_stop()
            sent = marlin.move_to(feed_mm_s=request.speed_mm_s, a=row.a_to_mm)
            ended = marlin.wait_idle()
            check_stop()
            anchor = RowAnchor(
                row.index, row.b_mm, row.a_from_mm, row.a_to_mm,
                request.speed_mm_s, plan.accel_mm_s2,
                sent.sent_s, ended.received_s,
            )
            motion = anchor.motion()
            if not collector.wait_past(motion.end_s + ROW_MARGIN_S):
                raise StreamFault(
                    f"row {row.index}: no samples for {CATCH_UP_S:g} s "
                    "after the row ended: the stream has stalled"
                )
            taken = collector.take(
                motion.start_s - ROW_MARGIN_S, motion.end_s + ROW_MARGIN_S
            )
            _check_range(taken, current_range_a, f"row {row.index}")
            expected = plan.stream_hz * motion.profile.duration_s
            if len(taken) < MIN_ROW_SAMPLE_SHARE * expected:
                raise StreamFault(
                    f"row {row.index}: {len(taken)} samples, expected about "
                    f"{expected:.0f} at {plan.stream_hz:g} Hz"
                )
            direction = motion.direction
            writer.write_row(
                anchor,
                [
                    _sample_row(
                        s, row.index, direction,
                        float(motion.a_at(h)), row.b_mm,
                    )
                    for s, h in taken
                ],
            )
            say(
                f"row {row.index + 1}/{len(rows)}: {len(taken)} samples"
            )
        status = "complete"
    except RunStopped:
        status = "stopped"
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


def _check_range(
    taken: list[tuple[StreamSample, float]],
    current_range_a: float | None,
    where: str,
) -> None:
    """A fixed range that clipped makes the data wrong, not just noisy."""
    if current_range_a is None or not taken:
        return
    peak = max(abs(s.current_a) for s, _ in taken)
    if peak >= SATURATION_SHARE * current_range_a:
        raise StreamFault(
            f"{where}: {peak * 1e6:.3g} uA reaches the end of the "
            f"{current_range_a * 1e6:g} uA range: use a larger "
            "--current-range"
        )


def _shut_down(
    devices: ScanDevices, *, moving: bool, say: Callable[[str], None]
) -> None:
    """Make everything safe, trying every step even if one fails."""
    steps: list[tuple[str, Callable[[], object]]] = []
    if moving:
        steps.append(("stop motion", devices.marlin.quickstop))
    steps += [
        ("laser off", devices.laser.off),
        ("SMU output off", devices.smu.output_off),  # stops the stream
    ]
    for name, step in steps:
        try:
            step()
        except Exception as exc:
            say(f"shutdown: {name} failed: {type(exc).__name__}: {exc}")


def _sample_row(
    sample: StreamSample,
    row: int,
    direction: int,
    a_mm: float,
    b_mm: float,
) -> SampleRow:
    return SampleRow(
        row, direction, sample.channel, sample.device_ms, sample.host_s,
        sample.current_a, sample.voltage_v, a_mm, b_mm,
    )


def run_header(
    machine: MachineConfig,
    plan: RasterPlan,
    laser: int,
    *,
    sample: str,
    simulated: bool,
    firmware: dict[str, str | None],
    provenance: dict[str, Any],
    current_range_a: float | None = DEFAULT_CURRENT_RANGE_A,
) -> dict[str, Any]:
    """The `# key: value` block at the top of a run file."""
    r = plan.request
    return {
        "sample": sample,
        "simulated": simulated,
        "started": datetime.datetime.now(datetime.UTC).isoformat(
            timespec="seconds"
        ),
        "app_version": version("multilbic"),
        "provenance": provenance,
        "firmware": firmware,
        "laser": laser,
        "wavelength_nm": machine.laser(laser).wavelength_nm,
        "frame_origin_ab_mm": list(r.frame.origin_ab_mm),
        "frame_size_mm": [r.frame.width_mm, r.frame.height_mm],
        "pixel_mm": r.pixel_mm,
        "pitch_mm": r.pitch_mm,
        "n_rows": len(plan.rows),
        "speed_mm_s": r.speed_mm_s,
        "serpentine": r.serpentine,
        "run_up_mm": plan.run_up_mm,
        "accel_mm_s2": plan.accel_mm_s2,
        "stream_hz": plan.stream_hz,
        "mains_hz": machine.mains_hz,
        "current_range_a": current_range_a,
        "ab_backlash_mm": machine.geometry.ab_backlash_mm,
        "estimate_s": round(plan.estimate_s, 1),
    }
