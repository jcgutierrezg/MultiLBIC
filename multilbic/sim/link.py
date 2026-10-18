"""
A `LineLink` wired to a simulated device instead of a serial port.

The driver under test is the real driver: it writes the same lines and
parses the same replies it would on the machine. Only the far end of the
cable is fake.
"""

from __future__ import annotations

import queue
import threading
from typing import Protocol

from multilbic.clock import SYSTEM_CLOCK, Clock
from multilbic.hardware.link import LinkClosed


class FakeDevice(Protocol):
    def attach(self, emit, clock: Clock) -> None:
        """Called once. `emit(line)` sends a line to the host."""
        ...

    def receive(self, line: str) -> None:
        """A line from the host. Must return promptly: a device that
        takes time to act queues the work for its own thread."""
        ...

    def shutdown(self) -> None: ...


_CLOSED = object()


class FakeLink:
    """Host side of the pair. Created by `connect()`."""

    def __init__(self, device: FakeDevice, clock: Clock):
        self._device = device
        self._clock = clock
        self._inbox: queue.Queue[object] = queue.Queue()
        self._closed = False
        self._lock = threading.Lock()

    def _emit(self, line: str) -> None:
        if not self._closed:
            self._inbox.put(line)

    def write_line(self, line: str) -> None:
        if self._closed:
            raise LinkClosed("link is closed")
        self._device.receive(line)

    def read_line(self, timeout: float) -> str | None:
        if self._closed and self._inbox.empty():
            raise LinkClosed("link is closed")
        try:
            item = self._inbox.get(
                timeout=max(0.0, self._clock.to_real(timeout))
            )
        except queue.Empty:
            return None
        if item is _CLOSED:
            raise LinkClosed("link is closed")
        assert isinstance(item, str)
        return item

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._inbox.put(_CLOSED)
        self._device.shutdown()


def connect(device: FakeDevice, clock: Clock = SYSTEM_CLOCK) -> FakeLink:
    """Plug a fake device in and return the host's end of the cable."""
    link = FakeLink(device, clock)
    device.attach(link._emit, clock)
    return link
