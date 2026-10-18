"""
The machine description: what is bolted together and where it is.

Why this exists
---------------
The old script kept laser positions, the AB centre and the port names as
module-level constants beside the GUI code. Changing a calibrated value
meant editing the program, and nothing checked the value made sense: a
typo in a laser position would have shown up as a map of the wrong part
of the sample.

So the values live in `machine.toml` and are loaded once into frozen
dataclasses. Loading is strict on purpose:

* an unknown key is an error, so a misspelt `safe_max_mm` cannot be
  silently ignored in favour of a default;
* every range is checked against the travel it has to fit in;
* the result is immutable, so a worker thread can hold it without a
  lock and nothing can edit it partway through a run.

Units are millimetres and mm/s, the units G-code speaks, and every field
name carries its unit.
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

DEFAULT_RESOURCE = "machine.toml"

#: The laser board drives six enables and a servo that turns 180 degrees.
LASER_NUMBERS = range(1, 7)
SERVO_RANGE_DEG = (0, 180)


class MachineConfigError(ValueError):
    """The machine file is missing a value, has an unknown one, or holds
    one that cannot be right. The message names the key."""


@dataclass(frozen=True)
class AbStage:
    steps_per_mm: int
    travel_mm: float
    centre_mm: tuple[float, float]
    safe_min_mm: float
    safe_max_mm: float
    max_feed_mm_s: float
    max_accel_mm_s2: float

    @property
    def microstep_mm(self) -> float:
        """The smallest possible move, and so the finest row pitch."""
        return 1.0 / self.steps_per_mm


@dataclass(frozen=True)
class XyStage:
    steps_per_mm: int
    travel_mm: tuple[float, float]
    max_feed_mm_s: float
    max_accel_mm_s2: float


@dataclass(frozen=True)
class Laser:
    number: int
    wavelength_nm: int
    servo_angle_deg: int
    xy_centre_mm: tuple[float, float]
    #: False while the position is still a placeholder.
    measured: bool


@dataclass(frozen=True)
class Ports:
    skr: str
    laser: str
    tft: str
    smu: str


@dataclass(frozen=True)
class MachineConfig:
    name: str
    ab: AbStage
    xy: XyStage
    lasers: tuple[Laser, ...]
    #: Keyed by `sys.platform` ("linux", "win32", ...).
    ports_by_platform: dict[str, Ports]
    baud: int

    def laser(self, number: int) -> Laser:
        for laser in self.lasers:
            if laser.number == number:
                return laser
        raise KeyError(f"no laser {number} in {self.name}")

    def ports(self, platform: str | None = None) -> Ports:
        """The ports for this platform, or all-empty if it has none."""
        key = platform or sys.platform
        return self.ports_by_platform.get(key, Ports("", "", "", ""))


def load(path: str | Path | None = None) -> MachineConfig:
    """Load a machine file, or the packaged default when `path` is None."""
    if path is None:
        text = (
            resources.files(__package__)
            .joinpath(DEFAULT_RESOURCE)
            .read_text(encoding="utf-8")
        )
        source = DEFAULT_RESOURCE
    else:
        text = Path(path).read_text(encoding="utf-8")
        source = str(path)
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise MachineConfigError(f"{source}: {exc}") from exc
    return parse(data, source)


def parse(data: dict[str, Any], source: str = "<dict>") -> MachineConfig:
    """Build and validate a MachineConfig from already-decoded TOML."""
    top = _Table(data, source)
    config = MachineConfig(
        name=top.read_str("name"),
        ab=_parse_ab(top.table("ab")),
        xy=_parse_xy(top.table("xy")),
        lasers=tuple(_parse_laser(t) for t in top.tables("lasers")),
        ports_by_platform={
            platform: _parse_ports(table)
            for platform, table in top.table("ports").subtables()
        },
        baud=top.table("serial").read_positive_int("baud"),
    )
    top.done()
    _check_lasers(config.lasers, source)
    return config


def _parse_ab(t: _Table) -> AbStage:
    ab = AbStage(
        steps_per_mm=t.read_positive_int("steps_per_mm"),
        travel_mm=t.read_positive_float("travel_mm"),
        centre_mm=t.read_pair("centre_mm"),
        safe_min_mm=t.read_float("safe_min_mm"),
        safe_max_mm=t.read_float("safe_max_mm"),
        max_feed_mm_s=t.read_positive_float("max_feed_mm_s"),
        max_accel_mm_s2=t.read_positive_float("max_accel_mm_s2"),
    )
    t.done()
    if not 0.0 <= ab.safe_min_mm < ab.safe_max_mm <= ab.travel_mm:
        raise t.error(
            f"safe range {ab.safe_min_mm}..{ab.safe_max_mm} mm must lie "
            f"inside 0..{ab.travel_mm} mm of travel"
        )
    for axis, value in zip("AB", ab.centre_mm, strict=True):
        if not ab.safe_min_mm < value < ab.safe_max_mm:
            raise t.error(
                f"centre_mm {axis}={value} is outside the safe range "
                f"{ab.safe_min_mm}..{ab.safe_max_mm} mm"
            )
    return ab


def _parse_xy(t: _Table) -> XyStage:
    xy = XyStage(
        steps_per_mm=t.read_positive_int("steps_per_mm"),
        travel_mm=t.read_pair("travel_mm"),
        max_feed_mm_s=t.read_positive_float("max_feed_mm_s"),
        max_accel_mm_s2=t.read_positive_float("max_accel_mm_s2"),
    )
    t.done()
    if min(xy.travel_mm) <= 0:
        raise t.error(f"travel_mm {xy.travel_mm} must be positive")
    return xy


def _parse_laser(t: _Table) -> Laser:
    laser = Laser(
        number=t.read_int("number"),
        wavelength_nm=t.read_positive_int("wavelength_nm"),
        servo_angle_deg=t.read_int("servo_angle_deg"),
        xy_centre_mm=t.read_pair("xy_centre_mm"),
        measured=t.read_bool("measured"),
    )
    t.done()
    if laser.number not in LASER_NUMBERS:
        raise t.error(
            f"laser number {laser.number} is not one of "
            f"{LASER_NUMBERS.start}..{LASER_NUMBERS.stop - 1}"
        )
    low, high = SERVO_RANGE_DEG
    if not low <= laser.servo_angle_deg <= high:
        raise t.error(
            f"laser {laser.number}: servo_angle_deg "
            f"{laser.servo_angle_deg} is outside {low}..{high}"
        )
    return laser


def _parse_ports(t: _Table) -> Ports:
    ports = Ports(
        skr=t.read_str("skr", allow_empty=True),
        laser=t.read_str("laser", allow_empty=True),
        tft=t.read_str("tft", allow_empty=True),
        smu=t.read_str("smu", allow_empty=True),
    )
    t.done()
    return ports


def _check_lasers(lasers: tuple[Laser, ...], source: str) -> None:
    if not lasers:
        raise MachineConfigError(f"{source}: no [[lasers]] defined")
    numbers = [laser.number for laser in lasers]
    duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
    if duplicates:
        raise MachineConfigError(
            f"{source}: laser numbers defined more than once: {duplicates}"
        )


class _Table:
    """One TOML table, read key by key and checked for leftovers.

    Every getter removes its key, so `done()` can report anything the
    file holds that the code never asked for, which is how a misspelt
    key is caught rather than ignored.
    """

    def __init__(self, data: Any, where: str):
        if not isinstance(data, dict):
            raise MachineConfigError(f"{where}: expected a table")
        self._data = dict(data)
        self._where = where

    def error(self, message: str) -> MachineConfigError:
        return MachineConfigError(f"{self._where}: {message}")

    def _take(self, key: str) -> Any:
        if key not in self._data:
            raise self.error(f"missing '{key}'")
        return self._data.pop(key)

    def done(self) -> None:
        if self._data:
            raise self.error(f"unknown key(s): {sorted(self._data)}")

    def table(self, key: str) -> _Table:
        return _Table(self._take(key), f"{self._where} [{key}]")

    def tables(self, key: str) -> list[_Table]:
        value = self._take(key)
        if not isinstance(value, list):
            raise self.error(f"'{key}' must be an array of tables")
        return [
            _Table(item, f"{self._where} [[{key}]] #{i + 1}")
            for i, item in enumerate(value)
        ]

    def subtables(self) -> list[tuple[str, _Table]]:
        items = [
            (key, _Table(value, f"{self._where}.{key}"))
            for key, value in self._data.items()
        ]
        self._data.clear()
        return items

    def read_str(self, key: str, allow_empty: bool = False) -> str:
        value = self._take(key)
        if not isinstance(value, str) or (not value and not allow_empty):
            raise self.error(f"'{key}' must be a non-empty string")
        return value

    def read_bool(self, key: str) -> bool:
        value = self._take(key)
        if not isinstance(value, bool):
            raise self.error(f"'{key}' must be true or false")
        return value

    def read_int(self, key: str) -> int:
        value = self._take(key)
        # bool is an int subclass; `true` is not a laser number.
        if isinstance(value, bool) or not isinstance(value, int):
            raise self.error(f"'{key}' must be an integer, got {value!r}")
        return value

    def read_positive_int(self, key: str) -> int:
        value = self.read_int(key)
        if value <= 0:
            raise self.error(f"'{key}' must be positive, got {value}")
        return value

    def read_float(self, key: str) -> float:
        value = self._take(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise self.error(f"'{key}' must be a number, got {value!r}")
        return float(value)

    def read_positive_float(self, key: str) -> float:
        value = self.read_float(key)
        if value <= 0:
            raise self.error(f"'{key}' must be positive, got {value}")
        return value

    def read_pair(self, key: str) -> tuple[float, float]:
        value = self._take(key)
        if (
            not isinstance(value, list)
            or len(value) != 2
            or any(
                isinstance(v, bool) or not isinstance(v, (int, float))
                for v in value
            )
        ):
            raise self.error(f"'{key}' must be two numbers, got {value!r}")
        return (float(value[0]), float(value[1]))
