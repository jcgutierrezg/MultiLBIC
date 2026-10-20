"""
One source of time for drivers, simulators and the scan.

Why this exists
---------------
Every timing question in this project - how long a row takes, when a
sample was taken, how long to wait for Marlin - has to give the same
answer in a simulated run as on the machine. If the drivers called
`time.monotonic()` directly, a simulated 15 s row would take 15 real
seconds, and a test suite exercising a few dozen of them would take
minutes.

So drivers and simulators take a `Clock`. On the machine that is
`SystemClock`. In tests it is `ScaledClock`, which runs simulated time
faster than real time: at a factor of 100, a 5 s stage move completes in
50 ms of wall time, and every timestamp, timeout and sleep agrees with
it because they all come from the same object.

`to_real()` converts a simulated duration into the real one, for the few
places that hand a timeout to something outside the clock (a queue
`get`, a serial read).
"""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float:
        """Monotonic seconds. Only differences are meaningful."""
        ...

    def sleep(self, seconds: float) -> None: ...

    def to_real(self, seconds: float) -> float:
        """The wall-clock length of a duration in this clock's seconds."""
        ...

    def wall_ms(self) -> int:
        """Unix time in milliseconds, for instruments that want one."""
        ...


class SystemClock:
    """Real time."""

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)

    def to_real(self, seconds: float) -> float:
        return seconds

    def wall_ms(self) -> int:
        return int(time.time() * 1000)


class ScaledClock:
    """Simulated time running `factor` times faster than real time.

    Starts at zero when created. Sleeping is real sleeping, shortened by
    the factor, so threads still interleave as they would on the
    machine, just sooner.

    A real sleep overshoots by about 0.5 ms on Windows, and the factor
    multiplies that: at 20x a sleep ends 10 ms of simulated time late.
    For device tests that is harmless. For the scan's timing tests it is
    not, because every sleep on a reply's way to the host adds simulated
    latency the test didn't inject. `precise=True` sleeps short and then
    yields in a loop until the exact moment, at the cost of CPU.
    """

    #: How early a precise sleep stops sleeping and starts yielding.
    PRECISE_SPIN_S = 0.0015

    def __init__(self, factor: float = 100.0, precise: bool = False):
        if factor <= 0:
            raise ValueError("factor must be positive")
        self.factor = factor
        self.precise = precise
        self._t0 = time.monotonic()
        self._wall0_ms = int(time.time() * 1000)

    def now(self) -> float:
        return (time.monotonic() - self._t0) * self.factor

    def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        real = seconds / self.factor
        if not self.precise:
            time.sleep(real)
            return
        deadline = time.monotonic() + real
        if real > self.PRECISE_SPIN_S:
            time.sleep(real - self.PRECISE_SPIN_S)
        while time.monotonic() < deadline:
            time.sleep(0)

    def to_real(self, seconds: float) -> float:
        return seconds / self.factor

    def wall_ms(self) -> int:
        return self._wall0_ms + int(self.now() * 1000)


SYSTEM_CLOCK = SystemClock()
