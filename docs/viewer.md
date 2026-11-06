---
type: guide
title: "The viewer"
---

# The viewer

A run's maps, read from its folder (D30). Phase 7 builds it a step at a
time ([plan](plan.md#phase-7-the-viewer-and-spectral-response)); this
page says what it does so far.

```bash
uv run multilbic view
```

```bash
uv run multilbic view ~/multilbic-runs/20261106T163140Z_full_test
```

Its own window, on the PC and on the Pi. It reads run folders and
nothing else: no device, no machine lock, so it can stay open beside
`multilbic gui`, even during a run. On the Pi, runs from the window are
in `~/multilbic-runs`; copy a folder to the PC by hand (USB stick or
`scp`) and open it there the same way.

## What it shows

- **Run** (left): the run, its sample, start, status and note, its size,
  pixel and row pitch; **Open folder...** and **Reload** (a run still
  going shows the rows written so far).
- **Lasers**: one per map in the folder, in its colour; keys **1-6**
  pick one too. Clipped attempts (D26) are listed, not shown; a file
  that can't be read is named with why, and the rest open.
- **Map** (middle): drawn as the machine window draws it, turned to
  `[display]`, on white paper. The unit follows the map (mA, µA, nA). The
  toolbar zooms and pans. Below it: the map's status, serpentine shift,
  baseline, noise floor and range.
- **Colour** (right): **Auto** (all but the extreme 1 % at either end),
  **Full** (smallest to largest), or typed limits (**Set**, in the map's
  unit), kept when another laser is picked.
- **Cursor**: where the pointer is on the sample (u along the rows, v
  across them, from the calibration corner) and the value there. Short
  gaps in a row are filled in the picture from their neighbours, never
  in the data: such a pixel reads "no samples in this pixel".
- **Profile**: drag across the map (with the toolbar's zoom and pan
  off) to draw a line; the map along it is plotted. The line stays when
  another laser is picked, so the same line can be read at every
  wavelength. **Clear** removes it.

## How long a folder takes to open

Every map is built again from its file, as `multilbic map` does. On the
PC: under 2 s for a 1-2 mm line-up run of six lasers; about 80 s for
`20261106T163140Z_full_test` (three lasers, 18 x 20 mm, 120 MB a file),
most of it the serpentine alignment (`scan/alignment.py`). The window
stays usable while a folder loads, and the footer says which file it is
reading.
