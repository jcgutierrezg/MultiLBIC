"""
The laser board: six lasers on a servo revolver, behind a Seeeduino Xiao.

Talks to firmware 2.x (`firmware/laser/`), whose protocol is one reply
line per command: a value, `OK ...` or `ERR <reason>`. The 1.x sketch
answered in free text and could not be queried. It is not supported.

Two checks happen at `open()`, because both failures would otherwise
show up only as a wrong map:

* the board identifies as `MultiLBIC-Laser`, so a wrong port fails now;
* the servo angles compiled into the firmware match `machine.toml`.

After a timeout the link is out of step (the reply may still arrive and
be read as the answer to the next command), so the driver refuses
further commands until `resync()`. SMUniversal learned this one the hard
way with the GSM-20H10.
"""

from __future__ import annotations

from dataclasses import dataclass

from multilbic.clock import SYSTEM_CLOCK, Clock
from multilbic.config.machine import MachineConfig
from multilbic.hardware.link import LineLink

FIRMWARE_PREFIX = "MultiLBIC-Laser,"
QUERY_TIMEOUT_S = 1.0
#: Margin on top of the settle time when selecting a laser.
SELECT_MARGIN_S = 1.0


class LaserBoardError(RuntimeError):
    """The board refused a command, or did not answer."""


@dataclass(frozen=True)
class LaserState:
    #: 0 when every laser is off.
    laser: int
    servo_angle_deg: int


class LaserBoard:
    def __init__(
        self,
        link: LineLink,
        machine: MachineConfig,
        clock: Clock = SYSTEM_CLOCK,
    ):
        self._link = link
        self._machine = machine
        self._clock = clock
        self._desynced = False
        self.firmware: str | None = None
        self.settle_ms: int | None = None

    def open(self) -> str:
        """Identify the board and check its servo angles. Returns the
        firmware id, e.g. `MultiLBIC-Laser,2.0.0`."""
        self.resync()
        ident = self.query("ID?")
        if not ident.startswith(FIRMWARE_PREFIX):
            raise LaserBoardError(
                f"not a MultiLBIC laser board (ID? answered {ident!r}): "
                f"wrong port, or 1.x firmware that needs updating"
            )
        self.firmware = ident
        angles = self.query("ANGLES?").split()[1:]
        expected = [
            str(self._machine.laser(n).servo_angle_deg)
            for n in range(1, len(angles) + 1)
        ]
        if angles != expected:
            raise LaserBoardError(
                f"firmware servo angles {angles} do not match "
                f"machine.toml {expected}"
            )
        self.settle_ms = int(self.query("SETTLE?").split()[1])
        return ident

    def close(self) -> None:
        self._link.close()

    def select(self, laser: int) -> None:
        """Turn on one laser (1-6), all others off. Blocks while the
        servo turns and settles."""
        self._machine.laser(laser)  # KeyError for a laser that isn't there
        settle = (self.settle_ms or 0) / 1000.0
        reply = self.query(f"LASER {laser}", settle + SELECT_MARGIN_S)
        self._expect(reply, f"OK LASER {laser}")

    def off(self) -> None:
        self._expect(self.query("OFF"), "OK OFF")

    def state(self) -> LaserState:
        parts = self.query("STATE?").split()
        if len(parts) != 3 or parts[0] != "STATE":
            raise LaserBoardError(f"unexpected STATE? reply {parts}")
        return LaserState(int(parts[1]), int(parts[2]))

    def set_settle(self, milliseconds: int) -> None:
        reply = self.query(f"SETTLE {int(milliseconds)}")
        self._expect(reply, f"OK SETTLE {int(milliseconds)}")
        self.settle_ms = int(milliseconds)

    # ---- wire ----

    def query(self, command: str, timeout: float = QUERY_TIMEOUT_S) -> str:
        """Send a command and return its one reply line."""
        if self._desynced:
            raise LaserBoardError(
                "link out of step after a timeout: call resync()"
            )
        self._link.write_line(command)
        deadline = self._clock.now() + timeout
        while True:
            remaining = deadline - self._clock.now()
            line = self._link.read_line(max(0.0, remaining))
            if line is None:
                self._desynced = True
                raise LaserBoardError(f"no reply to {command!r}")
            line = line.strip()
            if not line or line.startswith("READY "):
                continue  # a boot banner, not a reply
            if line.startswith("ERR"):
                raise LaserBoardError(f"{command!r} refused: {line}")
            return line

    def resync(self, quiet_s: float = 0.2) -> None:
        """Discard anything in flight until the line is quiet."""
        while self._link.read_line(quiet_s) is not None:
            pass
        self._desynced = False

    @staticmethod
    def _expect(reply: str, expected: str) -> None:
        if reply != expected:
            raise LaserBoardError(f"expected {expected!r}, got {reply!r}")
