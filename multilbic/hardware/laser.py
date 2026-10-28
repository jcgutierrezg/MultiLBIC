"""
The laser board: six lasers on a servo revolver, behind a Seeeduino Xiao.

Talks to firmware 2.x (`firmware/laser/`), whose protocol is one reply
line per command: a value, `OK ...` or `ERR <reason>`. The 1.x sketch
answered in free text and could not be queried. It is not supported.

Two checks happen at `open()`, because both failures would otherwise
show up only as a wrong map:

* the board identifies as `MultiLBIC-Laser`, so a wrong port fails now;
* the servo angles compiled into the firmware match `machine.toml`.

A laser switched back on too soon after going off comes back dim and
stays dim: laser 1 relit after up to 1 s dark gave 38 uA where 2 s or
more gave 86 uA, for as long as it stayed on (bench, 2026-10-27; laser 3
did not care). So the driver never relights a laser within
`[laser_board] relight_ms` of turning it off, waiting out the rest, and
`select` of the laser already on sends nothing (the firmware would turn
it off and on again).

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
        #: The lit laser (0 for none) and the servo's angle, as the
        #: board said at open() and as this driver has set them since.
        self._active = 0
        self._angle: int | None = None
        #: When each laser last went off, by this driver's clock.
        self._off_at: dict[int, float] = {}

    def open(self) -> str:
        """Identify the board, check its servo angles and apply the
        configured settle time. Returns the firmware id, e.g.
        `MultiLBIC-Laser,2.0.0`."""
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
        wanted = self._machine.laser_board.settle_ms
        if self.settle_ms != wanted:
            # The firmware forgets a runtime value on power-up, so the
            # configured one is applied every time.
            self.set_settle(wanted)
        state = self.state()
        self._active, self._angle = state.laser, state.servo_angle_deg
        return ident

    def close(self) -> None:
        self._link.close()

    def select(self, laser: int) -> None:
        """Turn on one laser (1-6), all others off. Blocks while the
        servo turns and settles, and until the laser has been off for
        `relight_ms`. Nothing is sent if it is on already."""
        spec = self._machine.laser(laser)  # KeyError if it isn't there
        if laser == self._active:
            return
        moves = spec.servo_angle_deg != self._angle
        settle = (self.settle_ms or 0) / 1000.0
        # The firmware turns everything off first, and the laser stays
        # dark while the servo settles: that counts towards the wait.
        wait = self.relight_wait_s(laser) - (settle if moves else 0.0)
        if wait > 0:
            self._clock.sleep(wait)
        self._went_off(self._clock.now())
        reply = self.query(f"LASER {laser}",
                           (settle if moves else 0.0) + SELECT_MARGIN_S)
        self._expect(reply, f"OK LASER {laser}")
        self._active, self._angle = laser, spec.servo_angle_deg

    def off(self) -> None:
        self._went_off(self._clock.now())
        self._expect(self.query("OFF"), "OK OFF")
        self._active = 0

    def relight_wait_s(self, laser: int) -> float:
        """How long `laser` must still stay dark before it may come on."""
        went_off = self._off_at.get(laser)
        if went_off is None:
            return 0.0
        relight = self._machine.laser_board.relight_ms / 1000.0
        return max(0.0, relight - (self._clock.now() - went_off))

    def _went_off(self, when: float) -> None:
        if self._active:
            self._off_at[self._active] = when

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
