"""
The photodiode under its two blades, in simulation (Phase 6).

A square chip with two blade edges crossing over it, one quarter open
(`config.machine.Photodiode`). The current is the share of a round
Gaussian spot that falls on the open quarter, times what the whole beam
gives (`full_a`), computed exactly as `sim.sample` does: along each
axis the open stretch runs from a chip edge to a blade edge, and the
share inside it is a difference of error functions.

The edges sit at different heights, so the spot is a different size at
each: the blade along B (its edge crossed by rows along A) is at the
sample's height, the blade along A `blade_a_above_mm` higher, and the
chip `chip_below_mm` lower, under its window. A laser's focus can be
moved (`focus_mm`, the height of its waist above the lower blade), and
the spot grows away from it as `sqrt(sigma0^2 + (divergence * dz)^2)`:
that is what focus assist (step 6) turns while it runs.

Positions are on the carriage, in calibration's frame (see
`scan.photodiode`); the rig works out which carriage point is under the
lit laser.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from multilbic.config.machine import MachineConfig, Photodiode

#: 10-90 % width of an edge over the spot's standard deviation.
WIDTH_PER_SIGMA = 2.563
#: A laser with no `spot_um` in machine.toml gets this 10-90 % width.
DEFAULT_SPOT_UM = 50.0
#: What each laser gives on the whole chip, A (bench, 2026-10-29, read
#: 2 s after lighting); 4-6 are unknown, so a middling guess.
BENCH_FULL_A = {1: -735e-6, 2: -6.5e-6, 3: -1.21e-3}
UNKNOWN_FULL_A = -100e-6


def _below(edge: float, x: float, sigma: float) -> float:
    """The share of a Gaussian at `x` that lies below `edge`."""
    if sigma <= 0:
        return 1.0 if x < edge else 0.0
    return 0.5 * (1.0 + math.erf((edge - x) / (sigma * math.sqrt(2.0))))


def _between(lo: float, sigma_lo: float, hi: float, sigma_hi: float,
             x: float) -> float:
    return max(0.0, _below(hi, x, sigma_hi) - _below(lo, x, sigma_lo))


@dataclass
class SimPhotodiode:
    #: Where the blade edges cross, on the carriage.
    corner_mm: tuple[float, float]
    #: The open side of each edge: +1 or -1, along A and B.
    open_signs: tuple[int, int]
    chip_mm: float
    blade_a_above_mm: float
    #: Each laser's current on the whole chip, A.
    full_a: dict[int, float]
    #: Each laser's spot standard deviation at its waist, mm.
    sigma_mm: dict[int, float]
    #: The chip's middle relative to the corner, mm.
    chip_offset_mm: tuple[float, float] = (0.0, 0.0)
    #: How far the chip is below the lower blade, under its window.
    chip_below_mm: float = 1.5
    #: How fast the spot's sigma grows away from the waist, mm per mm.
    divergence: float = 0.05
    #: Each laser's waist height above the lower blade; 0 is in focus
    #: on the sample's plane. Changed while the simulation runs to stand
    #: for turning a laser's focus.
    focus_mm: dict[int, float] = field(default_factory=dict)
    dark_a: float = 0.0

    @classmethod
    def from_config(cls, machine: MachineConfig,
                    photodiode: Photodiode | None = None) -> SimPhotodiode:
        """The photodiode as machine.toml has it, with each laser's spot
        from its `spot_um` and its current from the bench."""
        pd = photodiode or machine.photodiode
        if pd is None:
            raise ValueError("machine.toml has no [photodiode]")
        sigma = {
            laser.number: (laser.spot_um or DEFAULT_SPOT_UM) / 1000.0
            / WIDTH_PER_SIGMA
            for laser in machine.lasers
        }
        full = {laser.number: BENCH_FULL_A.get(laser.number, UNKNOWN_FULL_A)
                for laser in machine.lasers}
        return cls(pd.corner_ab_mm, pd.open_signs, pd.chip_mm,
                   pd.blade_a_above_mm, full, sigma)

    def sigma_at(self, laser: int, height_mm: float) -> float:
        """The spot's sigma at `height_mm` above the lower blade."""
        s0 = self.sigma_mm[laser]
        dz = height_mm - self.focus_mm.get(laser, 0.0)
        return math.hypot(s0, self.divergence * dz)

    def share(self, laser: int, a: float, b: float) -> float:
        """The share of the spot centred at carriage (a, b) that falls
        on the open quarter."""
        blade_b = self.sigma_at(laser, 0.0)  # edge along B: rows along A
        blade_a = self.sigma_at(laser, self.blade_a_above_mm)
        chip = self.sigma_at(laser, -self.chip_below_mm)
        shares = []
        for k, (x, blade_sigma) in enumerate(((a, blade_b), (b, blade_a))):
            edge = self.corner_mm[k]
            half = self.chip_mm / 2
            centre = edge + self.chip_offset_mm[k]
            if self.open_signs[k] < 0:
                shares.append(_between(centre - half, chip, edge,
                                       blade_sigma, x))
            else:
                shares.append(_between(edge, blade_sigma, centre + half,
                                       chip, x))
        return shares[0] * shares[1]

    def current(self, laser: int, a: float, b: float) -> float:
        """What it gives with `laser` lit and centred at carriage
        (a, b); 0 for an unknown laser."""
        if laser not in self.full_a:
            return self.dark_a
        return self.full_a[laser] * self.share(laser, a, b) + self.dark_a
