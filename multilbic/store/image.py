"""A map as a PNG, for a quick look without the viewer."""

from __future__ import annotations

from pathlib import Path

from multilbic.scan.mapping import MapResult


def save_png(result: MapResult, path: str | Path, title: str = "") -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    grid = result.grid
    rows, cols = grid.values.shape
    width, height = cols * grid.pixel_mm, rows * grid.pitch_mm
    figure, axes = plt.subplots(figsize=(8, max(2.5, 8 * height / width)))
    image = axes.imshow(
        grid.values * 1e9,
        origin="lower",
        extent=(0, width, 0, height),
        aspect="auto",
        interpolation="nearest",
        cmap="inferno",
    )
    axes.set_xlabel("u (mm, along A)")
    axes.set_ylabel("v (mm, along B)")
    shift = result.alignment
    note = (
        f"serpentine shift {shift.shift_mm * 1000:.1f} µm"
        if shift.found
        else "serpentine shift not found"
    )
    axes.set_title(f"{title}\n{note}" if title else note, fontsize=10)
    figure.colorbar(image, ax=axes, label="photocurrent (nA)")
    figure.tight_layout()
    path = Path(path)
    figure.savefig(path, dpi=120)
    plt.close(figure)
    return path
