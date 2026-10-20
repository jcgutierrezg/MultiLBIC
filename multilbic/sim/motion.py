"""
How Marlin moves a straight line, close enough to simulate a scan.

Used by the fake Marlin only. The scan's own timing model lives in
`multilbic.scan` (Phase 3) and is written separately on purpose: if both
used this module, a wrong assumption would be shared by the simulator and
the code it is supposed to check, and every test would pass.

What is modelled, from Marlin 2.1.2.4's planner:

* the feedrate is capped so no axis exceeds its own max feedrate, by
  scaling the whole move (Marlin does this; it never distorts the line);
* the acceleration is capped the same way per axis, and by
  `DEFAULT_ACCELERATION` (100 mm/s² on this machine);
* each move is a trapezoid, or a triangle if it is too short to reach
  cruise speed.

What is not: junction speeds between consecutive moves (every block here
starts and ends at rest), and S-curve acceleration (disabled on this
machine). The scan plans each row as a single move with run-up and
run-out inside it, so it never depends on a junction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

AXES = ("X", "Y", "Z", "A", "B")


@dataclass(frozen=True)
class AxisLimits:
    max_feed_mm_s: float
    max_accel_mm_s2: float


@dataclass(frozen=True)
class Block:
    """One planned straight move, positioned in time."""

    start: dict[str, float]
    end: dict[str, float]
    t_start: float
    distance_mm: float
    cruise_mm_s: float
    accel_mm_s2: float
    t_accel: float
    t_cruise: float

    @property
    def duration(self) -> float:
        return 2 * self.t_accel + self.t_cruise

    @property
    def t_end(self) -> float:
        return self.t_start + self.duration

    def distance_at(self, t: float) -> float:
        """Distance travelled along the line at time `t`."""
        dt = t - self.t_start
        if dt <= 0:
            return 0.0
        if dt >= self.duration:
            return self.distance_mm
        a, v, ta = self.accel_mm_s2, self.cruise_mm_s, self.t_accel
        if dt < ta:
            return 0.5 * a * dt * dt
        d_accel = 0.5 * a * ta * ta
        if dt < ta + self.t_cruise:
            return d_accel + v * (dt - ta)
        t_left = self.duration - dt
        return self.distance_mm - 0.5 * a * t_left * t_left

    def position_at(self, t: float) -> dict[str, float]:
        if self.distance_mm == 0:
            return dict(self.end)
        fraction = self.distance_at(t) / self.distance_mm
        return {
            axis: self.start[axis]
            + (self.end[axis] - self.start[axis]) * fraction
            for axis in self.start
        }


def plan(
    start: dict[str, float],
    end: dict[str, float],
    feed_mm_s: float,
    limits: dict[str, AxisLimits],
    default_accel_mm_s2: float,
    t_start: float,
) -> Block:
    """Plan a move from `start` to `end` requested at `feed_mm_s`."""
    deltas = {axis: end[axis] - start[axis] for axis in start}
    distance = math.sqrt(sum(d * d for d in deltas.values()))
    if distance == 0:
        return Block(start, end, t_start, 0.0, 0.0, 1.0, 0.0, 0.0)

    cruise = feed_mm_s
    accel = default_accel_mm_s2
    for axis, delta in deltas.items():
        if delta == 0:
            continue
        share = abs(delta) / distance
        cruise = min(cruise, limits[axis].max_feed_mm_s / share)
        accel = min(accel, limits[axis].max_accel_mm_s2 / share)

    d_accel = cruise * cruise / (2 * accel)
    if 2 * d_accel >= distance:
        # Triangle: never reaches cruise speed.
        t_accel = math.sqrt(distance / accel)
        cruise = accel * t_accel
        t_cruise = 0.0
    else:
        t_accel = cruise / accel
        t_cruise = (distance - 2 * d_accel) / cruise
    return Block(
        dict(start), dict(end), t_start, distance, cruise, accel,
        t_accel, t_cruise,
    )
