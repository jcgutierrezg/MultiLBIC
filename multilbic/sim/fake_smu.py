"""
A simulated miniSMU, standing in for the `minismu_py.SMU` object.

The instrument is driven through its vendor library rather than a text
protocol, so the fake replaces the library object, not the cable. It
implements the methods SMUniversal's driver calls for the setup
MultiLBIC does, and the streaming methods. `tests/test_smu.py` checks
that each one exists on the real `minismu_py.SMU` with the same
parameter names, so the two cannot drift apart silently.

Streaming is paced by the clock. Packets are written as bytes into a
fake serial port (`FakeSerial`, the library's `_connection`), in the
format the bench showed: `channel,ms,volts,amps,0`, with whole-
millisecond stamps from a device clock that can be given an offset, a
drift and a rate error. The current is `signal(channel, t)` plus noise;
the scan simulation (`multilbic.sim.rig`) plugs the stage position and a
synthetic sample into `signal`.

The noise can be shaped like the bench's (`docs/hardware.md`, contacted
cell at 0 V): white noise (`noise_a`), mains pickup at `mains_hz` and
its odd harmonics (`mains_a`), and slow drift made of a few sine waves
between 0.2 and 0.7 Hz (`drift_a`, RMS). Packets can also arrive in
bursts (`burst_s`): above 500 Hz the real one delivers about every
100 ms, keeping the average rate. A burst delays arrival, never the
timestamp. A stamp lag (`stamp_lag_s`) stamps each packet that long
after its current was measured, as the bench suggests the real one does
(stamped when sent, docs/hardware.md); it is what Phase 6's sync check
measures.
"""

from __future__ import annotations

import math
import random
import threading
from collections.abc import Callable

from minismu_py import SMUException

from multilbic.clock import Clock

#: The measurement ranges, by index, as the library numbers them.
CURRENT_RANGES_A = (1e-6, 25e-6, 650e-6, 15e-3, 180e-3)
#: The library's serial timeout: how long an empty read blocks.
READ_TIMEOUT_S = 1.0
#: How long the library waits for the line to go quiet after STREAM OFF.
DRAIN_TIMEOUT_S = 2.0


class FakeMiniSMU:
    def __init__(
        self,
        clock: Clock,
        *,
        firmware: str = "1.5.0",
        signal: Callable[[int, float], float] | None = None,
        noise_a: float = 0.0,
        device_offset_ms: float = 0.0,
        drift_ppm: float = 0.0,
        rate_error: float = 0.0,
        mains_a: float = 0.0,
        mains_hz: float = 50.0,
        drift_a: float = 0.0,
        burst_s: float = 0.0,
        stamp_lag_s: float = 0.0,
        seed: int = 0,
    ):
        self._clock = clock
        self.firmware = firmware
        self.signal = signal or (lambda channel, t: 0.0)
        self.noise_a = noise_a
        self.device_offset_ms = device_offset_ms
        self.drift_ppm = drift_ppm
        #: Delivered rate = requested * (1 + rate_error). The real one
        #: misses the requested rate by up to ~19% (bench, 2026-10-19).
        self.rate_error = rate_error
        self.mains_a = mains_a
        self.mains_hz = mains_hz
        self.drift_a = drift_a
        self.burst_s = burst_s
        self.stamp_lag_s = stamp_lag_s
        self._random = random.Random(seed)
        shape = random.Random(seed + 1)
        self._mains_phase = shape.uniform(0, 2 * math.pi)
        #: (frequency, phase) of each drift component, 0.2-0.7 Hz.
        self._drift_parts = [
            (shape.uniform(0.2, 0.7), shape.uniform(0, 2 * math.pi))
            for _ in range(4)
        ]
        self._lock = threading.Lock()
        self._base_ms = 0.0
        self._base_t = clock.now()
        self.voltage = {1: 0.0, 2: 0.0}
        self.enabled = {1: False, 2: False}
        self.mode = {1: "FVMI", 2: "FVMI"}
        self.current_limit = {1: 0.0, 2: 0.0}
        self.osr = {1: 0, 2: 0}
        self.autorange = {1: True, 2: True}
        self.current_range: dict[int, int | None] = {1: None, 2: None}
        #: A fault: on autorange, stay on this range (an index) and read
        #: no further than its end. Not seen on the real one (bench,
        #: 2026-10-27); it tests the check's re-read.
        self.autorange_stuck: int | None = None
        self.rate_hz = {1: 1000.0, 2: 1000.0}
        self._next_due: dict[int, float] = {}
        self._buffer = bytearray()
        #: The port the library reads, as `minismu_py.SMU._connection`.
        self._connection = FakeSerial(self)
        #: Put one unparseable line into the stream.
        self.garble_next = False
        #: Stop delivering packets (a hung instrument or cable).
        self.stalled = False
        self.closed = False

    # ---- device clock ----

    def device_ms(self, t: float) -> float:
        elapsed_ms = (t - self._base_t) * 1000.0
        return (
            self._base_ms
            + elapsed_ms * (1 + self.drift_ppm * 1e-6)
            + self.device_offset_ms
        )

    def true_time(self, device_ms: float) -> float:
        """The clock time a stamp was taken at: `device_ms` inverted,
        to within the stamp's whole-millisecond rounding. Simulation
        only, for checking a scan's clock map against the truth."""
        with self._lock:
            elapsed_ms = (
                device_ms - self.device_offset_ms - self._base_ms
            ) / (1 + self.drift_ppm * 1e-6)
            return self._base_t + elapsed_ms / 1000.0

    def _current(self, channel: int, t: float) -> float:
        if not self.enabled[channel]:
            return 0.0
        noise = self._random.gauss(0.0, self.noise_a) if self.noise_a else 0.0
        amps = self.signal(channel, t) + noise + self.interference(t)
        index = self.current_range[channel]
        if self.autorange[channel]:
            index = self.autorange_stuck
        if index is not None:
            # A fixed range reads no further than its end.
            limit = CURRENT_RANGES_A[index]
            amps = max(-limit, min(limit, amps))
        return amps

    def interference(self, t: float) -> float:
        """Mains and drift at time `t`: what no laser causes."""
        total = 0.0
        if self.mains_a:
            # The fundamental, with a third harmonic a fifth as strong.
            w = 2 * math.pi * self.mains_hz * t + self._mains_phase
            total += self.mains_a * (math.sin(w) + 0.2 * math.sin(3 * w))
        if self.drift_a:
            # Sum of n unit sines has RMS sqrt(n/2).
            scale = self.drift_a / math.sqrt(len(self._drift_parts) / 2)
            total += scale * sum(
                math.sin(2 * math.pi * f * t + phase)
                for f, phase in self._drift_parts
            )
        return total

    # ---- identity and setup (what UndalogicMiniSMU calls) ----

    def get_identity(self) -> str:
        return f"Undalogic Ltd,miniSMU MS01 v1.1,fake-0000,v{self.firmware}(sim)"

    def reset(self):
        for channel in (1, 2):
            self.enabled[channel] = False

    def set_mode(self, channel: int, mode: str):
        self.mode[channel] = mode

    def set_voltage(self, channel: int, voltage: float):
        self.voltage[channel] = voltage

    def set_current_protection(self, channel: int, current_limit: float):
        self.current_limit[channel] = current_limit

    def set_voltage_protection(self, channel: int, voltage_limit: float):
        pass

    def set_voltage_range(self, channel: int, range_type: str):
        pass

    def set_autorange(self, channel: int, enabled: bool):
        self.autorange[channel] = enabled

    def set_current_range(self, channel: int, range_index: int):
        self.current_range[channel] = range_index

    def set_current_range_by_limit(self, channel: int, max_current: float,
                                    disable_autorange: bool = True) -> int:
        fitting = [
            i for i, limit in enumerate(CURRENT_RANGES_A)
            if abs(max_current) <= limit
        ]
        if not fitting:
            raise ValueError(f"{max_current} A exceeds the largest range")
        index = fitting[0]
        if disable_autorange:
            self.autorange[channel] = False
        self.current_range[channel] = index
        return index

    def set_oversampling_ratio(self, channel: int, osr: int):
        self.osr[channel] = osr

    def enable_channel(self, channel: int):
        self.enabled[channel] = True

    def disable_channel(self, channel: int):
        self.enabled[channel] = False

    def get_fourwire_mode(self) -> bool:
        return False

    def disable_fourwire_mode(self):
        pass

    def measure_voltage_and_current(self, channel: int) -> tuple[float, float]:
        t = self._clock.now()
        volts = self.voltage[channel] if self.enabled[channel] else 0.0
        return volts, self._current(channel, t)

    def get_temperatures(self) -> tuple[float, float, float]:
        return 30.0, 30.0, 30.0

    def close(self):
        self.closed = True

    # ---- streaming ----

    def set_sample_rate(self, channel: int, rate: float):
        self.rate_hz[channel] = float(rate)

    def set_time(self, timestamp: int):
        with self._lock:
            self._base_ms = float(timestamp)
            self._base_t = self._clock.now()

    def start_streaming(self, channel: int):
        with self._lock:
            self._next_due[channel] = self._clock.now()

    def stop_streaming(self, channel: int):
        # The real library sends STREAM OFF, then waits up to 2 s for the
        # line to go quiet. If another channel is still streaming it never
        # does, and the library raises (bench, 2026-10-19).
        with self._lock:
            self._next_due.pop(channel, None)
            still_streaming = bool(self._next_due)
        if still_streaming:
            self._clock.sleep(DRAIN_TIMEOUT_S)
            raise SMUException(
                "Device still sending data after 2s; another channel may "
                "still be streaming"
            )
        self._drain_input()

    def _write_command(self, command: str):
        """The library's raw write, with no reply read. Only the stream
        switch-off is modelled, since that is all it is used for here.
        Packets already sent stay in the port's buffer, as on the wire."""
        text = command.strip().upper()
        if text.startswith("SOUR") and text.endswith(":DATA:STREAM OFF"):
            channel = int(text[4 : text.index(":")])
            with self._lock:
                self._next_due.pop(channel, None)

    def _drain_input(self):
        with self._lock:
            self._produce_locked()
            self._buffer.clear()

    def read_streaming_data(self) -> tuple[int, float, float, float]:
        """As `minismu_py` does it: one `readline()`, the first four
        fields, `SMUException` for anything that doesn't parse."""
        data = self._connection.readline().decode("utf-8", "replace").strip()
        parts = data.split(",")
        try:
            if len(parts) < 4:
                raise ValueError
            channel, timestamp, voltage, current = parts[:4]
            return int(channel), float(timestamp), float(voltage), float(current)
        except ValueError:
            raise SMUException(
                f"Failed to parse streaming data: {data!r}"
            ) from None

    # ---- packet production, shared by both read paths ----

    def _produce_locked(self) -> None:
        """Append every packet due by now to the port's buffer."""
        now = self._clock.now()
        while self._next_due and not self.stalled:
            channel = min(self._next_due, key=self._next_due.__getitem__)
            due = self._next_due[channel]
            if self._released(due + self.stamp_lag_s) > now:
                return
            if self.garble_next:
                self.garble_next = False
                self._buffer.extend(b"Z,?\n")
            interval = 1.0 / (self.rate_hz[channel] * (1 + self.rate_error))
            self._next_due[channel] = due + interval
            volts = self.voltage[channel] if self.enabled[channel] else 0.0
            # Whole milliseconds and a fifth field, as the bench showed.
            # Measured at `due`, stamped when sent.
            stamp = int(round(self.device_ms(due + self.stamp_lag_s)))
            amps = self._current(channel, due)
            self._buffer.extend(
                f"{channel},{stamp},{volts:.4e},{amps:.4e},0\n".encode()
            )

    def _released(self, due: float) -> float:
        """When a packet stamped at `due` reaches the port."""
        if not self.burst_s:
            return due
        return (math.floor(due / self.burst_s) + 1) * self.burst_s

    def _next_due_time(self) -> float | None:
        if not self._next_due:
            return None
        return self._released(min(self._next_due.values())
                              + self.stamp_lag_s)


class FakeSerial:
    """The USB serial port `minismu_py` holds as `_connection`.

    Bytes appear in it as the fake instrument streams, paced by the
    clock. `read()` and `in_waiting` behave like pyserial's, so the bulk
    reader in `SmuStream` and the library's per-line read are tested
    against the same bytes.
    """

    def __init__(self, device: FakeMiniSMU):
        self._device = device
        self.timeout = READ_TIMEOUT_S

    @property
    def in_waiting(self) -> int:
        with self._device._lock:
            self._device._produce_locked()
            return len(self._device._buffer)

    def read(self, size: int = 1) -> bytes:
        return self._read_until(lambda buffer: len(buffer) > 0, size)

    def readline(self) -> bytes:
        return self._read_until(lambda buffer: b"\n" in buffer, None)

    def reset_input_buffer(self) -> None:
        self._device._drain_input()

    def _read_until(self, ready, size: int | None) -> bytes:
        device, clock = self._device, self._device._clock
        deadline = clock.now() + self.timeout
        while True:
            with device._lock:
                device._produce_locked()
                buffer = device._buffer
                now = clock.now()
                if ready(buffer) or now >= deadline:
                    if size is None:
                        end = buffer.find(b"\n")
                        size = end + 1 if end >= 0 else len(buffer)
                    taken = bytes(buffer[:size])
                    del buffer[:size]
                    return taken
                next_due = device._next_due_time()
            wake = deadline if next_due is None else min(deadline, next_due)
            clock.sleep(max(wake - now, 1e-4))


class FakeMiniSMUTransport:
    """What SMUniversal's driver expects: an object with `.client`."""

    def __init__(self, client: FakeMiniSMU):
        self.client = client

    def close(self):
        self.client.close()
