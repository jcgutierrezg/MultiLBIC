"""
Lines of text over a serial port.

Marlin and the laser board both speak newline-terminated ASCII over USB
serial. Their drivers talk to a `LineLink` rather than to pyserial, so a
simulator can stand in for the cable: `multilbic.sim.link` provides the
same interface wired to a fake device. The miniSMU is different - it is
driven through its vendor library - and does not use this module.

A link carries lines and nothing else. It knows no G-code and no laser
commands. Timeouts are in the driver's clock seconds, so a simulated
link and a real one are called identically.
"""

from __future__ import annotations

import threading
from typing import Protocol

from multilbic.clock import SYSTEM_CLOCK, Clock


class LinkClosed(ConnectionError):
    """The link was closed, by us or by the device disappearing."""


class LineLink(Protocol):
    def write_line(self, line: str) -> None:
        """Send one line. The terminator is added here."""
        ...

    def read_line(self, timeout: float) -> str | None:
        """The next complete line without its terminator, or None if
        none arrived within `timeout` seconds of the link's clock."""
        ...

    def close(self) -> None: ...


class SerialLink:
    """A `LineLink` over a pyserial port.

    Partial lines are kept between reads, so a line that straddles a
    timeout is returned whole on a later call instead of in two pieces.
    Writes are serialised with a lock because Marlin's emergency stop is
    written from a different thread to its ordinary commands.
    """

    def __init__(self, port, clock: Clock = SYSTEM_CLOCK):
        # `port` is an open `serial.Serial`, or anything with read(),
        # write(), in_waiting, timeout and close(). Opened by the caller,
        # so tests can pass `serial.serial_for_url("loop://")`.
        self._port = port
        self._clock = clock
        self._buffer = bytearray()
        self._write_lock = threading.Lock()
        self._closed = False

    @classmethod
    def open(cls, device: str, baud: int, clock: Clock = SYSTEM_CLOCK):
        import serial

        return cls(serial.Serial(device, baud, timeout=0.05), clock)

    def write_line(self, line: str) -> None:
        if self._closed:
            raise LinkClosed("link is closed")
        data = (line + "\n").encode("ascii")
        with self._write_lock:
            try:
                self._port.write(data)
            except OSError as exc:
                raise LinkClosed(str(exc)) from exc

    def read_line(self, timeout: float) -> str | None:
        deadline = self._clock.now() + timeout
        while True:
            line = self._pop_line()
            if line is not None:
                return line
            if self._closed:
                raise LinkClosed("link is closed")
            remaining = deadline - self._clock.now()
            if remaining <= 0:
                return None
            self._port.timeout = min(self._clock.to_real(remaining), 0.05)
            try:
                waiting = self._port.in_waiting
                chunk = self._port.read(max(1, waiting))
            except (OSError, TypeError, AttributeError) as exc:
                # pyserial raises SerialException (an OSError) when the
                # device is unplugged, and TypeError/AttributeError when
                # the port was closed underneath a read.
                if self._closed:
                    raise LinkClosed("link is closed") from exc
                raise LinkClosed(str(exc)) from exc
            self._buffer.extend(chunk)

    def _pop_line(self) -> str | None:
        index = self._buffer.find(b"\n")
        if index < 0:
            return None
        raw = bytes(self._buffer[:index])
        del self._buffer[: index + 1]
        return raw.decode("ascii", errors="replace").rstrip("\r")

    def close(self) -> None:
        self._closed = True
        try:
            self._port.close()
        except OSError:
            pass
