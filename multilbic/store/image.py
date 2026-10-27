"""A map as a PNG, for a quick look without the viewer.

`view` turns the picture to match how the operator sees the stage:
which way +u (along the rows, A) and +v (across them, B) point on the
cell as seen at the machine. `[display]` in machine.toml holds it. The
axes keep their true u and v values; only their direction on the page
changes, and the calibration corner (u = v = 0) is marked.

`draw_map` does the drawing on any matplotlib axes; the window uses it
for the live map and the finished one, so all three look the same.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from multilbic.scan.mapping import MapResult

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.image import AxesImage

#: Plain mathematical axes: u to the right, v up.
DEFAULT_VIEW = ("right", "up")
_HORIZONTAL = ("left", "right")
CMAP = "inferno"


def draw_map(
    axes: Axes,
    values_a: np.ndarray,
    width_mm: float,
    height_mm: float,
    view: tuple[str, str] = DEFAULT_VIEW,
    **imshow: Any,
) -> AxesImage:
    """Draw `values_a[v, u]` (amps) in nA over the sample's true size,
    turned to `view`, with the corner marked. Returns the image, whose
    data a live display can replace (`image_data` gives it the right
    way round)."""
    u_points, v_points = view
    if u_points in _HORIZONTAL:
        x_size, y_size = width_mm, height_mm
        x_dir, y_dir = u_points, v_points
        x_label, y_label = "u (mm, along A: the rows)", "v (mm, along B)"
    else:
        x_size, y_size = height_mm, width_mm
        x_dir, y_dir = v_points, u_points
        x_label, y_label = "v (mm, along B)", "u (mm, along A: the rows)"
    shown = axes.imshow(
        image_data(values_a, view),
        origin="lower",
        extent=(0.0, x_size, 0.0, y_size),
        aspect="equal",
        interpolation="nearest",
        cmap=CMAP,
        **imshow,
    )
    # The image sits at its true coordinates; turning the axes round
    # turns the picture with them.
    if x_dir == "left":
        axes.invert_xaxis()
    if y_dir == "down":
        axes.invert_yaxis()
    axes.plot([0], [0], marker="+", color="cyan", markersize=14, mew=2)
    # The label goes on the map's side of the corner, whichever way the
    # axes are turned, so it never spills over the colour bar.
    dx = -6 if x_dir == "left" else 6
    dy = -6 if y_dir == "down" else 6
    axes.annotate("corner", (0, 0), color="cyan", fontsize=8,
                  xytext=(dx, dy), textcoords="offset points",
                  ha="right" if dx < 0 else "left",
                  va="top" if dy < 0 else "bottom",
                  annotation_clip=False)
    axes.set_xlabel(x_label)
    axes.set_ylabel(y_label)
    return shown


def image_data(values_a: np.ndarray, view: tuple[str, str]) -> np.ndarray:
    """`values_a[v, u]` in nA, transposed when u runs up or down."""
    values = np.asarray(values_a) * 1e9
    return values if view[0] in _HORIZONTAL else values.T


def save_png(
    result: MapResult,
    path: str | Path,
    title: str = "",
    view: tuple[str, str] = DEFAULT_VIEW,
) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    grid = result.grid
    rows, cols = grid.values.shape
    width, height = cols * grid.pixel_mm, rows * grid.pitch_mm
    x_size, y_size = (width, height) if view[0] in _HORIZONTAL \
        else (height, width)
    figure, axes = plt.subplots(
        figsize=(8, max(2.5, min(12.0, 8 * y_size / x_size)))
    )
    shown = draw_map(axes, grid.values, width, height, view)
    axes.set_title(f"{title}\n{shift_note(result)}" if title
                   else shift_note(result), fontsize=10)
    figure.colorbar(shown, ax=axes, label="photocurrent (nA)")
    figure.tight_layout()
    path = Path(path)
    figure.savefig(path, dpi=120)
    plt.close(figure)
    return path


def shift_note(result: MapResult) -> str:
    shift = result.alignment
    return (
        f"serpentine shift {shift.shift_mm * 1000:.1f} µm"
        if shift.found
        else "serpentine shift not found"
    )
