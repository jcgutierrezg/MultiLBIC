# Legacy code

The code as it stood before the rewrite, kept for reference only. Nothing
here is imported or run. Delete each file once the rewrite covers what it
did.

| File | What it is |
|---|---|
| `MultiLBIC_Control.py` | The Tk GUI version (2556 lines, Feb 2026). It never ran a real sweep: `sweep()` is commented out, `sweep2` uses variables that do not exist, `sweep3` (the streaming version) is never called, the laser and TFT serial writes are commented out, and polled "measurements" are random numbers. |
| `Serial_control.py` | The earlier version with no GUI, driven from the TFT35 with `W`/`D`/`L`/`OK` text commands; one-corner calibration. |
| `Serial_control test2.py` | An older version still: four-corner calibration. |
| `Plotter test.py` | A standalone scatter viewer for the old `.txt` output. |

Two byte-identical copies (`MultiLBIC_Control - Copy.py` and
`Serial_control (Copy).py`) were deleted during the 2026-10-17 cleanup.
