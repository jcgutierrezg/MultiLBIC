"""
Bringing a point on the photodiode under a laser (Phase 6).

The photodiode sits about 37 mm from the AB centre along A, far outside
AB's travel, so XY has to make up most of it. A point on the carriage is
given in calibration's frame (`config.machine.Photodiode`): the AB
position that would put it under a laser with XY at that laser's
`xy_centre_mm`. Moving XY by d moves the carriage by d along the AB
axis it is aligned with (`[geometry] x_along`, `y_along`), so any split
with

    AB + xy_to_ab(XY - xy_centre) = point

works. Of those, `reach` keeps each AB axis as close to its centre as
X and Y's travel allows, which leaves A and B the most room to scan
both ways. For the lasers near X's end (1-3, bench 2026-10-29) that
puts X at its end and A just below its safe limit, and the room left
upwards is the margin: a scan across an edge needs some on both sides.
"""

from __future__ import annotations

from dataclasses import dataclass

from multilbic.config.machine import MachineConfig
from multilbic.scan.geometry import ab_to_xy, xy_to_ab


class OutOfReach(ValueError):
    """No XY and AB within travel put that point under that laser."""


@dataclass(frozen=True)
class Reach:
    laser: int
    xy_mm: tuple[float, float]
    ab_mm: tuple[float, float]
    #: How far A and B can move down and up from `ab_mm` within their
    #: safe range: (A down, A up, B down, B up).
    room_mm: tuple[float, float, float, float]

    @property
    def xyab(self) -> tuple[float, float, float, float]:
        return (*self.xy_mm, *self.ab_mm)


def _xy_for(machine: MachineConfig, ab_axis: int) -> tuple[int, int]:
    """(XY axis index, sign) of the XY axis that moves along AB axis
    `ab_axis` (0 for A, 1 for B)."""
    g = machine.geometry
    for xy_axis, along in enumerate((g.x_along, g.y_along)):
        if along[1] == "AB"[ab_axis]:
            return xy_axis, 1 if along[0] == "+" else -1
    raise AssertionError("x_along and y_along name both AB axes")


def reach(
    machine: MachineConfig, laser: int, point_ab: tuple[float, float],
    *, room_mm: float | tuple[float, float] = 0.0,
) -> Reach:
    """X, Y, A and B that put `point_ab` (carriage frame) under `laser`,
    each AB axis as near its centre as XY's travel allows, with at least
    `room_mm` left to A and B's safe limits both ways (one for both, or
    (A, B)). Raises `OutOfReach` if there is none."""
    rooms = room_mm if isinstance(room_mm, tuple) else (room_mm, room_mm)
    ab = machine.ab
    centre = machine.laser(laser).xy_centre_mm
    travel = machine.xy.travel_mm
    chosen = [0.0, 0.0]
    for k in (0, 1):
        j, s = _xy_for(machine, k)
        # xy_j = centre_j + s * (point_k - ab_k) must lie in 0..travel_j.
        if s > 0:
            lo = point_ab[k] - (travel[j] - centre[j])
            hi = point_ab[k] + centre[j]
        else:
            lo = point_ab[k] - centre[j]
            hi = point_ab[k] + (travel[j] - centre[j])
        lo = max(lo, ab.safe_min_mm + rooms[k])
        hi = min(hi, ab.safe_max_mm - rooms[k])
        if lo > hi + 1e-9:
            raise OutOfReach(
                f"laser {laser} cannot reach {'AB'[k]} {point_ab[k]:.2f} "
                f"on the carriage with {rooms[k]:g} mm of room: short by "
                f"{lo - hi:.3f} mm"
            )
        hi = max(hi, lo)
        chosen[k] = min(max(ab.centre_mm[k], lo), hi)
    a, b = chosen
    dx, dy = ab_to_xy(machine.geometry.x_along, machine.geometry.y_along,
                      point_ab[0] - a, point_ab[1] - b)
    x = min(max(centre[0] + dx, 0.0), travel[0])
    y = min(max(centre[1] + dy, 0.0), travel[1])
    return Reach(
        laser, (x, y), (a, b),
        (a - ab.safe_min_mm, ab.safe_max_mm - a,
         b - ab.safe_min_mm, ab.safe_max_mm - b),
    )


def span(
    machine: MachineConfig, laser: int,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """The carriage points `laser` can reach along A and along B, each
    (low, high): AB's safe range widened by all of XY's travel."""
    ab = machine.ab
    centre = machine.laser(laser).xy_centre_mm
    travel = machine.xy.travel_mm
    out = []
    for k in (0, 1):
        j, s = _xy_for(machine, k)
        lo_xy, hi_xy = -centre[j], travel[j] - centre[j]
        if s < 0:
            lo_xy, hi_xy = -hi_xy, -lo_xy
        out.append((ab.safe_min_mm + lo_xy, ab.safe_max_mm + hi_xy))
    return out[0], out[1]


def carriage_point(
    machine: MachineConfig, laser: int, xyab: tuple[float, float, float, float],
) -> tuple[float, float]:
    """The inverse: which carriage point (calibration's frame) is under
    `laser` with the stage at X, Y, A, B."""
    x, y, a, b = xyab
    cx, cy = machine.laser(laser).xy_centre_mm
    da, db = xy_to_ab(machine.geometry.x_along, machine.geometry.y_along,
                      x - cx, y - cy)
    return a + da, b + db


def open_quarter_middle(machine: MachineConfig) -> tuple[float, float]:
    """The middle of the photodiode's open quarter, on the carriage:
    where a laser lands fully on the chip, away from every edge."""
    pd = machine.photodiode
    if pd is None:
        raise ValueError("machine.toml has no [photodiode]")
    sa, sb = pd.open_signs
    quarter = pd.chip_mm / 4
    return (pd.corner_ab_mm[0] + sa * quarter,
            pd.corner_ab_mm[1] + sb * quarter)
