"""
A simulated laser board running firmware 2.0.0.

Mirrors `firmware/laser/MultiLBIC_Laser/MultiLBIC_Laser.ino` line for
line: the same replies, the same settle skipped when the servo is
already at the angle, and the same single-threaded behaviour (nothing is
answered while the servo settles).
"""

from __future__ import annotations

import queue
import threading

from multilbic.clock import Clock

FIRMWARE_ID = "MultiLBIC-Laser,2.0.0"
LASER_ANGLES = (150, 90, 30, 150, 90, 30)
START_ANGLE = 90
MAX_SETTLE_MS = 10000


class FakeLaserBoard:
    def __init__(
        self,
        *,
        firmware_id: str = FIRMWARE_ID,
        angles: tuple[int, ...] = LASER_ANGLES,
        settle_ms: int = 2000,
    ):
        self.firmware_id = firmware_id
        self.angles = angles
        self.settle_ms = settle_ms
        self.active = 0
        self.servo_angle = START_ANGLE
        #: (clock time, laser) every time the lit laser changes.
        self.history: list[tuple[float, int]] = []
        self.silent = False
        #: Every command line from the host, in order.
        self.received: list[str] = []
        self._inbox: queue.Queue[str | None] = queue.Queue()
        self._emit = None
        self._clock: Clock | None = None

    def attach(self, emit, clock: Clock) -> None:
        self._emit = emit
        self._clock = clock
        threading.Thread(
            target=self._run, name="fake-laser", daemon=True
        ).start()
        emit(f"READY {self.firmware_id}")

    def receive(self, line: str) -> None:
        self.received.append(line.strip())
        self._inbox.put(line)

    def shutdown(self) -> None:
        self._inbox.put(None)

    def _run(self) -> None:
        while True:
            line = self._inbox.get()
            if line is None:
                return
            command = line.strip()
            if command and not self.silent:
                reply = self._handle(command)
                assert self._emit is not None
                self._emit(reply)

    def _set_active(self, laser: int) -> None:
        self.active = laser
        assert self._clock is not None
        self.history.append((self._clock.now(), laser))

    def _handle(self, command: str) -> str:
        if command == "ID?":
            return self.firmware_id
        if command == "STATE?":
            return f"STATE {self.active} {self.servo_angle}"
        if command == "ANGLES?":
            return "ANGLES " + " ".join(str(a) for a in self.angles)
        if command == "SETTLE?":
            return f"SETTLE {self.settle_ms}"
        if command.startswith("SETTLE "):
            value = command[7:]
            if not value.isdigit() or int(value) > MAX_SETTLE_MS:
                return "ERR BAD_VALUE"
            self.settle_ms = int(value)
            return f"OK SETTLE {self.settle_ms}"
        if command in ("OFF", "LASER 0"):
            self._set_active(0)
            return "OK OFF"
        if command.startswith("LASER "):
            value = command[6:]
            if not value.isdigit() or not 1 <= int(value) <= len(self.angles):
                return "ERR BAD_LASER"
            laser = int(value)
            self._set_active(0)
            target = self.angles[laser - 1]
            if target != self.servo_angle:
                self.servo_angle = target
                assert self._clock is not None
                self._clock.sleep(self.settle_ms / 1000.0)
            self._set_active(laser)
            return f"OK LASER {laser}"
        return "ERR UNKNOWN"
