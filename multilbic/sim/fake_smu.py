"""
A simulated miniSMU, standing in for the `minismu_py.SMU` object.

The instrument is driven through its vendor library rather than a text
protocol, so the fake replaces the library object, not the cable. It
implements the methods SMUniversal's driver calls for the setup
MultiLBIC does, and the streaming methods. `tests/test_smu.py` checks
that each one exists on the real `minismu_py.SMU` with the same
parameter names, so the two cannot drift apart silently.

Streaming is paced by the clock: packets are produced at the set rate in
simulated time, stamped by a device clock that can be given an offset
and a drift, and carry `signal(channel, t)` plus noise as the current.
Phase 3 plugs the stage position and a synthetic sample into `signal`.
"""

from __future__ import annotations

import random
import threading
from collections.abc import Callable

from minismu_py import SMUException

from multilbic.clock import Clock

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
        seed: int = 0,
    ):
        self._clock = clock
        self.firmware = firmware
        self.signal = signal or (lambda channel, t: 0.0)
        self.noise_a = noise_a
        self.device_offset_ms = device_offset_ms
        self.drift_ppm = drift_ppm
        self._random = random.Random(seed)
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
        self.rate_hz = {1: 1000.0, 2: 1000.0}
        self._next_due: dict[int, float] = {}
        #: Raise one unparseable packet on the next streaming read.
        self.garble_next = False
        self.closed = False

    # ---- device clock ----

    def device_ms(self, t: float) -> float:
        elapsed_ms = (t - self._base_t) * 1000.0
        return (
            self._base_ms
            + elapsed_ms * (1 + self.drift_ppm * 1e-6)
            + self.device_offset_ms
        )

    def _current(self, channel: int, t: float) -> float:
        if not self.enabled[channel]:
            return 0.0
        noise = self._random.gauss(0.0, self.noise_a) if self.noise_a else 0.0
        return self.signal(channel, t) + noise

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

    def _write_command(self, command: str):
        """The library's raw write, with no reply read. Only the stream
        switch-off is modelled, since that is all it is used for here."""
        text = command.strip().upper()
        if text.startswith("SOUR") and text.endswith(":DATA:STREAM OFF"):
            channel = int(text[4 : text.index(":")])
            with self._lock:
                self._next_due.pop(channel, None)

    def read_streaming_data(self) -> tuple[int, float, float, float]:
        with self._lock:
            if self.garble_next:
                self.garble_next = False
                raise SMUException("Failed to parse streaming data: 'Z,?'")
            if not self._next_due:
                due = None
            else:
                channel = min(self._next_due, key=self._next_due.__getitem__)
                due = self._next_due[channel]
                self._next_due[channel] = due + 1.0 / self.rate_hz[channel]
        if due is None:
            self._clock.sleep(READ_TIMEOUT_S)
            raise SMUException("Failed to parse streaming data: ''")
        wait = due - self._clock.now()
        if wait > 0:
            self._clock.sleep(wait)
        volts = self.voltage[channel] if self.enabled[channel] else 0.0
        return channel, self.device_ms(due), volts, self._current(channel, due)


class FakeMiniSMUTransport:
    """What SMUniversal's driver expects: an object with `.client`."""

    def __init__(self, client: FakeMiniSMU):
        self.client = client

    def close(self):
        self.client.close()
