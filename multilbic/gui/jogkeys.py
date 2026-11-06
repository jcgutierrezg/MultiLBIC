"""
Which axis a jog arrow moves, so that the stage moves the way the arrow
points, as the operator sees it at the machine.

The stage, not the spot: the builder asked for it (2026-10-28) after
the arrows first moved the spot over the sample, which is the opposite
way and felt backwards at the machine. The spot moves across the sample
against the arrow.

`[display]` in machine.toml says which way +A (`u_points`) and +B
(`v_points`) move the spot over the sample as seen at the machine, so
the stage moves the opposite way; `[geometry]` says which AB axis each
XY axis moves the sample along (`x_along`, `y_along`). On this machine
+A and +X move the spot left (bench, 2026-10-23), so the stage right:
the right arrow is +A in AB mode and +X in XY mode, as the command
line's `d` is. +B and +Y move the spot down, the stage up. A machine
with swapped or reversed axes gets its arrows right from the same two
tables.

In the window, `w a s d` are arrows too (up, left, down, right).
"""

from __future__ import annotations

from multilbic.config.machine import MachineConfig

DIRECTIONS = ("up", "down", "left", "right")
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}
#: Tk keysyms that jog, and the direction they mean.
KEYS = {
    "Up": "up", "Down": "down", "Left": "left", "Right": "right",
    "w": "up", "s": "down", "a": "left", "d": "right",
    "W": "up", "S": "down", "A": "left", "D": "right",
}
#: The steps the window offers, mm; `e` cycles through them.
STEPS_MM = (0.01, 0.1, 1.0, 10.0)
PAIRS = ("xy", "ab")


def jog_for(direction: str, pair: str, machine: MachineConfig) -> tuple[str, int]:
    """(axis, sign) that moves the stage `direction`, with `pair` "xy"
    or "ab"."""
    if direction not in OPPOSITE:
        raise ValueError(f"no direction {direction!r}")
    ab_axis, ab_sign = _ab_for(direction, machine)
    if pair == "ab":
        return ab_axis.lower(), ab_sign
    if pair != "xy":
        raise ValueError(f"no axis pair {pair!r}")
    g = machine.geometry
    for xy_axis, along in (("x", g.x_along), ("y", g.y_along)):
        sign, axis = (1 if along[0] == "+" else -1), along[1]
        if axis == ab_axis:
            return xy_axis, ab_sign * sign
    raise ValueError(f"no XY axis moves along {ab_axis}: check [geometry]")


def _ab_for(direction: str, machine: MachineConfig) -> tuple[str, int]:
    d = machine.display
    for axis, spot in (("A", d.u_points), ("B", d.v_points)):
        stage = OPPOSITE[spot]  # the stage moves against the spot
        if direction == stage:
            return axis, 1
        if direction == spot:
            return axis, -1
    raise ValueError(
        f"[display] u_points={d.u_points!r}, v_points={d.v_points!r} "
        f"leave {direction!r} without an axis"
    )


def arrow_label(direction: str, pair: str, machine: MachineConfig) -> str:
    """'+A', '-X': what an arrow button does, for its face."""
    axis, sign = jog_for(direction, pair, machine)
    return f"{'+' if sign > 0 else '-'}{axis.upper()}"
