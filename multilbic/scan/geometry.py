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


# ---- XY placement (Phase 4) ----
#
# XY carries the whole AB gantry, so moving XY moves the sample under the
# beam just as moving AB does, along the AB axis that `x_along` and
# `y_along` name. A point of the carriage is described by the AB
# position that would put it under a laser if XY sat at that laser's
# `xy_centre_mm`: `carriage = ab + M (xy - laser_xy)`, with M the signed
# swap the two settings describe.
#
# Corner calibration records XY and AB with the corner under the
# reference laser. For each laser, XY is then chosen so the sample's
# centre sits at the AB centre, and AB rasters around it, so every map
# gets the full AB range wherever the sample was put down. The frame in
# AB is the same for every laser; only XY differs, and how well maps
# from different lasers line up rests on the lasers' `xy_centre_mm`
# (measured properly in Phase 6).


class GeometryError(ValueError):
    pass


def _matrix(x_along: str, y_along: str) -> tuple[tuple[int, int], ...]:
    """M with (da, db) = M (dx, dy)."""
    m = [[0, 0], [0, 0]]
    for column, along in enumerate((x_along, y_along)):
        sign = 1 if along[0] == "+" else -1
        row = 0 if along[1] == "A" else 1
        m[row][column] = sign
    return (m[0][0], m[0][1]), (m[1][0], m[1][1])


def xy_to_ab(
    x_along: str, y_along: str, dx: float, dy: float
) -> tuple[float, float]:
    (a, b), (c, d) = _matrix(x_along, y_along)
    return a * dx + b * dy, c * dx + d * dy


def ab_to_xy(
    x_along: str, y_along: str, da: float, db: float
) -> tuple[float, float]:
    # M is a signed swap, so its inverse is its transpose.
    (a, b), (c, d) = _matrix(x_along, y_along)
    return a * da + c * db, b * da + d * db


@dataclass(frozen=True)
class Calibration:
    """Where the sample is, as recorded at the machine."""

    sample: str
    reference_laser: int
    #: The reference laser's xy_centre_mm when this was recorded.
    reference_xy_mm: tuple[float, float]
    #: Stage position with the corner under the reference laser. The
    #: corner is the one the sample extends from towards +A and +B.
    corner_xy_mm: tuple[float, float]
    corner_ab_mm: tuple[float, float]
    width_mm: float
    height_mm: float
    x_along: str
    y_along: str

    def __post_init__(self) -> None:
        if self.width_mm <= 0 or self.height_mm <= 0:
            raise GeometryError("a sample needs a positive width and height")

    @property
    def corner_carriage_mm(self) -> tuple[float, float]:
        da, db = xy_to_ab(
            self.x_along, self.y_along,
            self.corner_xy_mm[0] - self.reference_xy_mm[0],
            self.corner_xy_mm[1] - self.reference_xy_mm[1],
        )
        return self.corner_ab_mm[0] + da, self.corner_ab_mm[1] + db

    def to_dict(self) -> dict[str, object]:
        return {
            "sample": self.sample,
            "reference_laser": self.reference_laser,
            "reference_xy_mm": list(self.reference_xy_mm),
            "corner_xy_mm": list(self.corner_xy_mm),
            "corner_ab_mm": list(self.corner_ab_mm),
            "size_mm": [self.width_mm, self.height_mm],
            "x_along": self.x_along,
            "y_along": self.y_along,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Calibration:
        def pair(key: str) -> tuple[float, float]:
            a, b = data[key]
            return float(a), float(b)

        width, height = data["size_mm"]
        return cls(
            sample=str(data["sample"]),
            reference_laser=int(data["reference_laser"]),
            reference_xy_mm=pair("reference_xy_mm"),
            corner_xy_mm=pair("corner_xy_mm"),
            corner_ab_mm=pair("corner_ab_mm"),
            width_mm=float(width),
            height_mm=float(height),
            x_along=str(data["x_along"]),
            y_along=str(data["y_along"]),
        )


@dataclass(frozen=True)
class Placement:
    """Where to put XY for one laser, and the sample's frame in AB."""

    laser: int
    xy_mm: tuple[float, float]
    frame: SampleFrame


def place(
    calibration: Calibration,
    laser_xy_mm: tuple[float, float],
    ab_centre_mm: tuple[float, float],
    laser: int,
) -> Placement:
    """XY that puts the sample's centre at the AB centre under `laser`
    (whose `xy_centre_mm` is `laser_xy_mm`)."""
    c = calibration
    corner = c.corner_carriage_mm
    centre = (corner[0] + c.width_mm / 2, corner[1] + c.height_mm / 2)
    dx, dy = ab_to_xy(
        c.x_along, c.y_along,
        centre[0] - ab_centre_mm[0], centre[1] - ab_centre_mm[1],
    )
    xy = (laser_xy_mm[0] + dx, laser_xy_mm[1] + dy)
    frame = SampleFrame.centred(ab_centre_mm, c.width_mm, c.height_mm)
    return Placement(laser, xy, frame)
