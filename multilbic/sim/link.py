"""
A `LineLink` wired to a simulated device instead of a serial port.

The driver under test is the real driver: it writes the same lines and
parses the same replies it would on the machine. Only the far end of the
cable is fake.

Replies can be delayed on their way to the host (`latency_s`, plus up to
`jitter_s` more at random), as USB and the host's reader thread delay
them on the machine. Order is kept, as on a serial line. The scan's row
anchors are reply arrival times, so this is how its tests inject
latency.
"""

from __future__ import annotations

import queue
import random
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

    def __init__(
        self,
        device: FakeDevice,
        clock: Clock,
        latency_s: float = 0.0,
        jitter_s: float = 0.0,
        seed: int = 0,
    ):
        self._device = device
        self._clock = clock
        self._inbox: queue.Queue[object] = queue.Queue()
        self._closed = False
        self._lock = threading.Lock()
        self.latency_s = latency_s
        self.jitter_s = jitter_s
        self._random = random.Random(seed)
        self._last_due = float("-inf")

    def _emit(self, line: str) -> None:
        if self._closed:
            return
        if not (self.latency_s or self.jitter_s):
            self._inbox.put(line)
            return
        with self._lock:
            delay = self.latency_s + self._random.uniform(0, self.jitter_s)
            # A later line never overtakes an earlier one.
            due = max(self._clock.now() + delay, self._last_due)
            self._last_due = due
        self._inbox.put((due, line))

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
        if isinstance(item, tuple):
            due, item = item
            self._clock.sleep(due - self._clock.now())
        assert isinstance(item, str)
        return item

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._inbox.put(_CLOSED)
        self._device.shutdown()


def connect(
    device: FakeDevice,
    clock: Clock = SYSTEM_CLOCK,
    latency_s: float = 0.0,
    jitter_s: float = 0.0,
) -> FakeLink:
    """Plug a fake device in and return the host's end of the cable."""
    link = FakeLink(device, clock, latency_s, jitter_s)
    device.attach(link._emit, clock)
    return link
