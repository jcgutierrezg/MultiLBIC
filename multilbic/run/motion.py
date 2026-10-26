"""
Placing moves that always end the same way.

Lead screws have backlash: where the stage stops depends on which way
it last moved. Marlin's compensation is effectively off on this machine
(correction 0), and it lists 0.2 mm on X/Y. So every move that places
something - XY under a laser, AB at a row's start, a jog during corner
calibration - finishes moving **up** on each axis it moves, from at
least the take-up distance below (`[geometry]` in machine.toml). The
stage then always sits the same side of its backlash, and calibration
and scan agree.

Rows themselves are the exception: they alternate direction on A, and
the serpentine alignment measures what that does.
"""

from __future__ import annotations

import threading

from multilbic.config.machine import MachineConfig
from multilbic.hardware.marlin import Marlin

#: XY moves only to place things, so it can go faster than AB.
XY_TRAVEL_FEED_MM_S = 10.0
#: AB placing moves; 5 mm/s stays below the noisy 6 mm/s (D9).
AB_TRAVEL_FEED_MM_S = 5.0


class RunStopped(Exception):
    """The operator asked to stop."""


def check(stop: threading.Event | None) -> None:
    """Raise `RunStopped` if `stop` is set."""
    if stop is not None and stop.is_set():
        raise RunStopped("stopped by the operator")


def approach(
    marlin: Marlin,
    machine: MachineConfig,
    *,
    x: float | None = None,
    y: float | None = None,
    a: float | None = None,
    b: float | None = None,
    stop: threading.Event | None = None,
) -> dict[str, float]:
    """Move to the given axes' targets, each arriving moving up, and
    wait until the stage is there. XY moves first, then AB. Returns the
    commanded position.

    `stop` is checked before every move and after the wait: whoever sets
    it also quickstops Marlin, and an approach of several moves must not
    carry on with the next one. Raises `RunStopped` then."""
    g = machine.geometry
    start = marlin.position()
    lower = {
        "X": 0.0, "Y": 0.0,
        "A": machine.ab.safe_min_mm, "B": machine.ab.safe_min_mm,
    }
    for group, take_up, feed in (
        ({"X": x, "Y": y}, g.xy_take_up_mm, XY_TRAVEL_FEED_MM_S),
        ({"A": a, "B": b}, g.ab_take_up_mm, AB_TRAVEL_FEED_MM_S),
    ):
        targets = {k: v for k, v in group.items() if v is not None}
        if not targets:
            continue
        # Any axis that would arrive moving down, or not far enough up,
        # first goes below its target.
        below = {
            axis: max(target - take_up, lower[axis])
            for axis, target in targets.items()
            if start[axis] > target - take_up
        }
        if below:
            check(stop)
            _move(marlin, feed, below)
        check(stop)
        _move(marlin, feed, targets)
    marlin.wait_idle()
    check(stop)
    return marlin.position()


def _move(marlin: Marlin, feed: float, target: dict[str, float]) -> None:
    marlin.move_to(feed_mm_s=feed, **{k.lower(): v for k, v in target.items()})
