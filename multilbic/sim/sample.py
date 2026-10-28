"""
A synthetic solar-cell sample with a known pattern, for simulated scans.

The pattern is made of rectangles, each with a photocurrent that depends
on wavelength. Overlapping rectangles add, so a finger (a metal line that
shades the cell) is a rectangle with the opposite current of the cell
under it, and a defect is one that removes part of it.

The laser spot is a round Gaussian. Blurring a rectangle with a Gaussian
has an exact answer (a product of error functions), so the current at
any spot position is computed, not sampled, and the 50 % point of every
blurred edge is exactly where the edge is. That is what the scan's tests
measure against.

Coordinates are the sample frame of `multilbic.scan.geometry`: `u` along
A and `v` along B, in mm from the sample's corner.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Patch:
    """A rectangle of photocurrent. `amps` is the current at the peak
    of its spectral response; the response falls off as a Gaussian of
    `width_nm` around `peak_nm`."""

    u0: float
    u1: float
    v0: float
    v1: float
    amps: float
    peak_nm: float
    width_nm: float = 250.0

    def amps_at(self, wavelength_nm: float) -> float:
        x = (wavelength_nm - self.peak_nm) / self.width_nm
        return self.amps * math.exp(-0.5 * x * x)


def _blurred_step(x0: float, x1: float, x: float, sigma: float) -> float:
    """The fraction of a Gaussian spot at `x` that falls inside
    [x0, x1]."""
    if sigma <= 0:
        return 1.0 if x0 <= x < x1 else 0.0
    k = 1.0 / (sigma * math.sqrt(2.0))
    return 0.5 * (math.erf((x1 - x) * k) - math.erf((x0 - x) * k))


@dataclass(frozen=True)
class SyntheticSample:
    width_mm: float
    height_mm: float
    patches: tuple[Patch, ...]
    #: The spot's standard deviation (its 1/e² radius is twice this).
    spot_sigma_mm: float = 0.005
    #: What flows with the laser off.
    dark_a: float = 0.0

    def current(self, wavelength_nm: float, u: float, v: float) -> float:
        """Photocurrent with the spot centred at (u, v)."""
        s = self.spot_sigma_mm
        total = 0.0
        for p in self.patches:
            fu = _blurred_step(p.u0, p.u1, u, s)
            if fu == 0.0:
                continue
            fv = _blurred_step(p.v0, p.v1, v, s)
            total += p.amps_at(wavelength_nm) * fu * fv
        return total + self.dark_a

    @classmethod
    def default(
        cls,
        width_mm: float = 1.0,
        height_mm: float = 0.3,
        cell_a: float = 1e-6,
        spot_sigma_mm: float = 0.005,
    ) -> SyntheticSample:
        """Two cells side by side with different spectra, fingers across
        both, and a partial defect in the second cell. Scales with the
        size, so the same shapes appear in a 1 mm and a 10 mm sample.

        The fingers run along B, so every row crosses them: they are the
        sharp A edges the position tests and the serpentine alignment
        use. The cells' top and bottom are the B edges."""
        w, h = width_mm, height_mm
        margin_u, margin_v = 0.1 * w, 0.15 * h
        gap = 0.06 * w
        finger = 0.025 * w
        left = (margin_u, w / 2 - gap / 2)
        right = (w / 2 + gap / 2, w - margin_u)
        v_lo, v_hi = margin_v, h - margin_v
        patches = [
            Patch(left[0], left[1], v_lo, v_hi, cell_a, peak_nm=650.0),
            Patch(right[0], right[1], v_lo, v_hi, 0.7 * cell_a, peak_nm=520.0),
        ]
        for (u0, u1), peak, amps in (
            (left, 650.0, cell_a),
            (right, 520.0, 0.7 * cell_a),
        ):
            span = u1 - u0
            for fraction in (1 / 3, 2 / 3):
                c = u0 + fraction * span
                patches.append(
                    Patch(c - finger / 2, c + finger / 2, v_lo, v_hi,
                          -amps, peak_nm=peak)
                )
        # A defect: 60 % of the second cell's current lost over a patch.
        du = right[1] - right[0]
        patches.append(
            Patch(right[0] + 0.05 * du, right[0] + 0.25 * du,
                  v_lo + 0.3 * (v_hi - v_lo), v_hi,
                  -0.6 * 0.7 * cell_a, peak_nm=520.0)
        )
        return cls(w, h, tuple(patches), spot_sigma_mm)

    @classmethod
    def straight_edge(
        cls,
        width_mm: float = 2.0,
        height_mm: float = 2.0,
        edge_u_mm: float = 1.0,
        cell_a: float = 1e-6,
        spot_sigma_mm: float = 0.016,
    ) -> SyntheticSample:
        """A cell that ends in one straight edge along B at
        `edge_u_mm`, current on the low-u side: the test cell's straight
        right edge (`stdtest-redge`), where the sync check is made. The
        spot defaults to laser 2's after refocusing (41 um 10-90 %)."""
        far = 10 * max(width_mm, height_mm)
        return cls(width_mm, height_mm, (
            Patch(-far, edge_u_mm, -far, far, cell_a, peak_nm=650.0,
                  width_nm=1e6),
        ), spot_sigma_mm)

    def u_edges(self) -> list[float]:
        """Every A position where a patch begins or ends, sorted."""
        return sorted({e for p in self.patches for e in (p.u0, p.u1)})

    def v_edges(self) -> list[float]:
        return sorted({e for p in self.patches for e in (p.v0, p.v1)})
