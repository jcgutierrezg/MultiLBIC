"""
A sample's current ranges, checked at calibration (D25).

How bright a laser looks depends on the sample as much as on the laser
(its response at that wavelength, contacts, area, bias), so the range
each laser maps with is measured on the sample: the stage runs a coarse
grid over it under each laser - three lines along A and three along B,
at 1/6, 1/2 and 5/6 of the sample - while single readings are taken on
autorange (single readings, not the stream, so autoranging costs
nothing), and the range is the smallest that holds `HEADROOM` times the
brightest reading. The calibration file keeps the result.

No devices here: the choice, the grid, the time it takes, the record.
`Calibrator.check_ranges` does the moving and reading.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

from multilbic.run.rows import AUTORANGE_CURRENT_LIMIT_A, FIXED_RANGES_A
from multilbic.scan.geometry import SampleFrame

#: The range holds this many times the brightest reading: laser 2's
#: output doubled over its first two minutes on (bench, 2026-10-23), and
#: the check happens right after switching each laser on.
HEADROOM = 3.0
#: Where the grid's lines cross the sample, as fractions of its size.
GRID_FRACTIONS = (1 / 6, 1 / 2, 5 / 6)
#: How fast the stage runs the grid.
CHECK_FEED_MM_S = 2.0
#: Time per laser beyond the lines (laser switch, placing, the moves
#: between lines), a rough figure for the estimate shown beforehand.
CHECK_OVERHEAD_S = 8.0
#: A reading this close to the check's current limit means the laser
#: may be brighter still.
AT_LIMIT_SHARE = 0.98


@dataclass(frozen=True)
class RangeCheck:
    laser: int
    #: The brightest reading on the grid, A (absolute value).
    peak_a: float
    #: The range chosen for it.
    range_a: float
    bias_v: float
    #: When it was checked, ISO 8601.
    when: str
    readings: int
    #: The brightest reading hit the check's own current limit, so the
    #: laser may be brighter: the range is a floor, and the run's
    #: step-up covers the rest (D26).
    at_limit: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "peak_a": self.peak_a, "range_a": self.range_a,
            "bias_v": self.bias_v, "when": self.when,
            "readings": self.readings, "at_limit": self.at_limit,
        }

    @classmethod
    def from_dict(cls, laser: int, data: dict[str, Any]) -> RangeCheck:
        return cls(
            laser=laser, peak_a=float(data["peak_a"]),
            range_a=float(data["range_a"]), bias_v=float(data["bias_v"]),
            when=str(data["when"]), readings=int(data.get("readings", 0)),
            at_limit=bool(data.get("at_limit", False)),
        )


def choose_range(peak_a: float, headroom: float = HEADROOM) -> float:
    """The smallest fixed range that holds `headroom` x `peak_a`; the
    largest if none does."""
    need = abs(peak_a) * headroom
    for candidate in FIXED_RANGES_A:
        if candidate >= need:
            return candidate
    return FIXED_RANGES_A[-1]


def check_result(
    laser: int, readings: list[float], bias_v: float,
    limit_a: float = AUTORANGE_CURRENT_LIMIT_A,
) -> RangeCheck:
    """What a laser's grid of readings says about its range."""
    if not readings:
        raise ValueError(f"laser {laser}: no readings on the grid")
    peak = max(abs(r) for r in readings)
    at_limit = peak >= AT_LIMIT_SHARE * limit_a
    range_a = choose_range(peak)
    if at_limit:
        # Brighter than the check could see: at least the range above
        # its limit.
        range_a = max(range_a, choose_range(limit_a, headroom=1.01))
    return RangeCheck(
        laser, peak, range_a, bias_v,
        datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        len(readings), at_limit,
    )


def grid_lines(
    frame: SampleFrame,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """The grid's six lines in AB, each (start, end): three along A,
    then three along B, each line starting where the last ended where it
    can, to keep the moves between them short."""
    a0, b0 = frame.origin_ab_mm
    w, h = frame.width_mm, frame.height_mm
    lines = []
    for i, f in enumerate(GRID_FRACTIONS):
        b = b0 + f * h
        ends = ((a0, b), (a0 + w, b))
        lines.append(ends if i % 2 == 0 else ends[::-1])
    for i, f in enumerate(GRID_FRACTIONS):
        a = a0 + f * w
        ends = ((a, b0), (a, b0 + h))
        lines.append(ends if i % 2 == 0 else ends[::-1])
    return lines


def check_duration_s(frame: SampleFrame, lasers: int) -> float:
    """Roughly how long checking `lasers` lasers takes."""
    per_laser = (len(GRID_FRACTIONS) * (frame.width_mm + frame.height_mm)
                 / CHECK_FEED_MM_S + CHECK_OVERHEAD_S)
    return per_laser * lasers


def ranges_to_dict(checks: dict[int, RangeCheck]) -> dict[str, Any]:
    return {str(n): c.as_dict() for n, c in sorted(checks.items())}


def ranges_from_dict(data: dict[str, Any] | None) -> dict[int, RangeCheck]:
    if not data:
        return {}
    return {int(n): RangeCheck.from_dict(int(n), d) for n, d in data.items()}
