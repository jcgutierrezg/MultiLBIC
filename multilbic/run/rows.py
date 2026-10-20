"""
One laser's map, row by row, written to a run file as it goes.

This is the part of a run that Phase 3 needs to make a map: position the
stage, record a dark baseline, light the laser, then for each row step B,
move along A at the scan speed, and anchor the row on the `M400` that
ends it. The SMU streams throughout; after each row the samples taken
while it moved are written out with its anchor.

What it does not do yet is Phase 4: homing and corner calibration, the
loop over lasers, a Stop button, and fault handling beyond the basics.
It does make sure that however it ends, the laser is off, the stream is
stopped, the SMU output is off and the file says whether it finished.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any

import numpy as np

from multilbic.clock import Clock
from multilbic.config.machine import MachineConfig
from multilbic.hardware.laser import LaserBoard
from multilbic.hardware.marlin import Marlin
from multilbic.hardware.smu import PhotocurrentSmu, StreamSample
from multilbic.scan.mapping import BASELINE_ROW
from multilbic.scan.raster import TRAVEL_FEED_MM_S, RasterPlan
from multilbic.scan.timing import ClockTracker, RowAnchor
from multilbic.store.runfile import RunWriter, SampleRow

#: Approach the first row from below in B, so B's backlash is taken up
#: the same way for every row (rows always step +B).
B_TAKE_UP_MM = 0.1
#: Samples this close outside a row's move are kept with it.
ROW_MARGIN_S = 0.02
#: How long to wait for the stream to catch up with the end of a row.
#: It arrives in bursts about every 100 ms.
CATCH_UP_S = 2.0
DEFAULT_BASELINE_S = 3.0


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
    say: Callable[[str], None] = lambda text: None,
) -> dict[str, Any]:
    """Run one laser's map. Returns the trailer written to the file."""
    marlin, board, smu = devices.marlin, devices.laser, devices.smu
    request = plan.request
    rows = plan.rows
    safe_min = machine.ab.safe_min_mm
    status = "incomplete"
    trailer: dict[str, Any] = {}
    collector = _Collector(smu, clock)
    try:
        first = rows[0]
        marlin.move_to(
            feed_mm_s=TRAVEL_FEED_MM_S,
            a=first.a_from_mm,
            b=max(first.b_mm - B_TAKE_UP_MM, safe_min),
        )
        marlin.wait_idle()
        marlin.move_to(feed_mm_s=TRAVEL_FEED_MM_S, b=first.b_mm)
        marlin.wait_idle()

        board.off()
        smu.prepare(bias_v=bias_v)
        smu.output_on()
        smu.stream.start(channels=(1,), rate_hz=plan.stream_hz)

        say(f"baseline: {baseline_s:g} s with the laser off")
        t0 = clock.now()
        clock.sleep(baseline_s)
        t1 = clock.now()
        collector.wait_past(t1)
        stage = marlin.position()
        writer.write_samples(
            [
                _sample_row(s, BASELINE_ROW, 0, stage["A"], stage["B"])
                for s, _ in collector.take(t0, t1)
            ]
        )

        say(f"laser {laser} on")
        board.select(laser)

        for row in rows:
            if row.index > 0:
                if not request.serpentine:
                    marlin.move_to(
                        feed_mm_s=TRAVEL_FEED_MM_S, a=row.a_from_mm
                    )
                marlin.move_to(feed_mm_s=TRAVEL_FEED_MM_S, b=row.b_mm)
                marlin.wait_idle()
            sent = marlin.move_to(feed_mm_s=request.speed_mm_s, a=row.a_to_mm)
            ended = marlin.wait_idle()
            anchor = RowAnchor(
                row.index, row.b_mm, row.a_from_mm, row.a_to_mm,
                request.speed_mm_s, plan.accel_mm_s2,
                sent.sent_s, ended.received_s,
            )
            motion = anchor.motion()
            if not collector.wait_past(motion.end_s + ROW_MARGIN_S):
                say(f"row {row.index}: the stream fell behind")
            taken = collector.take(
                motion.start_s - ROW_MARGIN_S, motion.end_s + ROW_MARGIN_S
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
    finally:
        try:
            board.off()
        finally:
            try:
                smu.output_off()  # stops the stream first
            finally:
                if collector.received:
                    trailer["clock_map"] = collector.tracker.fit().as_dict()
                trailer["samples_received"] = collector.received
                writer.finish(status, trailer)
    return trailer


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
        "estimate_s": round(plan.estimate_s, 1),
    }
