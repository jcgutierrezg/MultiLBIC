"""A map as a PNG, for a quick look without the viewer.

`view` turns the picture to match how the operator sees the stage:
which way +u (along the rows, A) and +v (across them, B) point on the
cell as seen at the machine. `[display]` in machine.toml holds it. The
axes keep their true u and v values; only their direction on the page
changes, and the calibration corner (u = v = 0) is marked.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from multilbic.scan.mapping import MapResult

#: Plain mathematical axes: u to the right, v up.
DEFAULT_VIEW = ("right", "up")
_HORIZONTAL = ("left", "right")


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
    u_points, v_points = view
    values = grid.values * 1e9  # [v, u]
    if u_points in _HORIZONTAL:
        image, x_size, y_size = values, width, height
        x_dir, y_dir = u_points, v_points
        x_label, y_label = "u (mm, along A: the rows)", "v (mm, along B)"
    else:
        image, x_size, y_size = values.T, height, width
        x_dir, y_dir = v_points, u_points
        x_label, y_label = "v (mm, along B)", "u (mm, along A: the rows)"
    figure, axes = plt.subplots(
        figsize=(8, max(2.5, min(12.0, 8 * y_size / x_size)))
    )
    shown = axes.imshow(
        np.asarray(image),
        origin="lower",
        extent=(0.0, x_size, 0.0, y_size),
        aspect="equal",
        interpolation="nearest",
        cmap="inferno",
    )
    # The image sits at its true coordinates; turning the axes round
    # turns the picture with them.
    if x_dir == "left":
        axes.invert_xaxis()
    if y_dir == "down":
        axes.invert_yaxis()
    axes.plot([0], [0], marker="+", color="cyan", markersize=14, mew=2)
    axes.annotate("corner", (0, 0), color="cyan", fontsize=8,
                  xytext=(6, 6), textcoords="offset points",
                  annotation_clip=False)
    axes.set_xlabel(x_label)
    axes.set_ylabel(y_label)
    shift = result.alignment
    note = (
        f"serpentine shift {shift.shift_mm * 1000:.1f} µm"
        if shift.found
        else "serpentine shift not found"
    )
    axes.set_title(f"{title}\n{note}" if title else note, fontsize=10)
    figure.colorbar(shown, ax=axes, label="photocurrent (nA)")
    figure.tight_layout()
    path = Path(path)
    figure.savefig(path, dpi=120)
    plt.close(figure)
    return path
