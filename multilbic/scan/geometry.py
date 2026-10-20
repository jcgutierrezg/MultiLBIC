"""
Coordinate frames.

**Machine AB** is where Marlin puts the raster stage, in mm. The beam is
fixed in space: with XY at a laser's `xy_centre_mm`, that laser hits the
AB carriage at a fixed point, and a feature of the sample is "at" the AB
position that brings it under the beam.

**Sample frame** (`u`, `v`, in mm) has its origin at the sample's corner:
`u` along A and `v` along B, so `a = origin_a + u` and
`b = origin_b + v`. The corner's AB position comes from corner
calibration (Phase 4): the corner is jogged under the beam and the AB
position read. A map in this frame is the sample as the beam sees it,
which may be mirrored relative to looking down on the stage; that is a
display question, left to the viewer.

The frame has no rotation. The raster always runs along A, so a sample
placed at an angle is scanned at that angle; correcting it would only
re-label pixels, and is left until a real map shows it is needed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SampleFrame:
    """Where the sample sits in AB, and its size."""

    origin_ab_mm: tuple[float, float]
    width_mm: float
    height_mm: float

    def __post_init__(self) -> None:
        if self.width_mm <= 0 or self.height_mm <= 0:
            raise ValueError("a sample needs a positive width and height")

    def to_ab(self, u: float, v: float) -> tuple[float, float]:
        return self.origin_ab_mm[0] + u, self.origin_ab_mm[1] + v

    def to_uv(self, a: float, b: float) -> tuple[float, float]:
        return a - self.origin_ab_mm[0], b - self.origin_ab_mm[1]

    @classmethod
    def centred(
        cls,
        centre_ab_mm: tuple[float, float],
        width_mm: float,
        height_mm: float,
    ) -> SampleFrame:
        """A frame whose centre is at `centre_ab_mm`, as for a sample
        placed in the middle of the stage."""
        return cls(
            (centre_ab_mm[0] - width_mm / 2, centre_ab_mm[1] - height_mm / 2),
            width_mm,
            height_mm,
        )
