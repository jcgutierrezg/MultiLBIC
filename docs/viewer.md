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

Its own window, on the PC and on the Pi. It needs no device and takes
no machine lock, so it can stay open beside `multilbic gui`, even during
a run. It reads run folders, and writes into them only each laser's
alignment file (below). On the Pi, runs from the window are
in `~/multilbic-runs`; copy a folder to the PC by hand (USB stick or
`scp`) and open it there the same way.

## What it shows

- **Run** (left): the run, its sample, start, status and note, its size,
  pixel and row pitch; **Open folder...** and **Reload** (a run still
  going shows the rows written so far).
- **Lasers**: one per map in the folder, in its colour; keys **1-6**
  pick one too, and show it alone. Clipped attempts (D26) are listed, not shown; a file
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
- **Alignment**: how the map's serpentine shift was found: computed
  (by the run, or by the viewer for a run made before 0.7.4) or set by
  hand, with which version and when. **Re-align** searches for it
  again with the code as it is now; **Set shift** builds the map with
  the shift typed (µm) and keeps it. Either is saved beside the laser's
  file and used from then on, by the viewer, `multilbic map` and the
  window's "Open run file" alike ([scan](scan.md#the-alignment-beside-it)).
- **Line or area** (**Drag draws**: a line, or an area), with the
  toolbar's zoom and pan off:
  - **a line: profile**: drag across the map to draw a line; the map
    along it is plotted. The line stays when another laser is picked,
    so the same line can be read at every wavelength.
  - **an area: spectrum**: click a pixel, or drag a box; every laser's
    value there is plotted at its wavelength (below).

  The line and the area each stay until cleared, whatever the view;
  **Clear** clears the one the mode draws.

## Comparing lasers

Above the map:

- **One laser**: the laser picked in the list (or with keys 1-6).
- **Side by side**: every laser of the run, each in its own panel, laid
  out as big as the area allows, all in one unit. **One colour scale**
  puts every panel on the same limits, so brighter is brighter across
  wavelengths; unticked, each panel gets its own, so each shows its own
  detail. Typed limits apply to every panel. A click on a panel makes
  that laser the current one: the one the Alignment section is about.
- **Ratio**: one laser over another, pixel by pixel, picked in the two
  boxes. A pixel is blank where the laser below gives under 5 % of its
  own top value (off the cell, a dead region), or where either has no
  samples: dividing by next to nothing shows only noise.

The cursor reads every laser shown (and the ratio), and the profile
plots each laser's along the same line in its own colour, or the ratio.
On `20261106T163140Z_full_test`, laser 6 (848 nm) over laser 1 (444 nm)
is about 3.9 across the cell; the finger edges show as thin stripes,
the two spots being different sizes.

## The spectrum

In area mode, a click picks the pixel under it and a drag a box (drawn
dashed on every panel, to the edges of the pixels it counts). For each
laser of the run, whatever the view, the plot shows its value there at
its wavelength: for a box, the median over its pixels, with bars from
the 16th to the 84th percentile (a normal spread's one standard
deviation, without outliers pulling it). It follows **Show**: EQE in %,
or photocurrent in the run's unit. A laser with nothing there (no EQE,
or no samples in the area) is left out and named.

On `20261106T163140Z_full_test`, a 3.6 x 3.0 mm box on the cell gives
-0.64, -1.38 and -2.35 mA at 444, 652 and 848 nm: photocurrent, as that
run has no power readings to make EQE from.

## EQE

**Show: Photocurrent / EQE**, under the views. EQE works in every view
(one laser, side by side, ratio), the cursor and the profile, in %.

A pixel's EQE is the cell's current over the photodiode's, at the
moment that row was scanned, times the photodiode's response to that
laser and 1239.84 / wavelength (`scan/eqe.py`):

- **The photodiode's current**: the power read before the map and after
  it (D31), dark taken out, a straight line between them in time, row by
  row. A laser whose output drifts during its map keeps a steady EQE (a
  simulated laser drifting 8 % a second: the current rose 6 % from the
  first rows across the cell to the last, the EQE 0.1 %).
- **The photodiode's response** (A/W), in this order: measured with the
  power meter, as `machine.toml` had it when the run was made; measured
  since, as `machine.toml` has it now (said so); or the S1223-01's
  typical curve from Hamamatsu's datasheet (KPIN1050E02), said so. Below
  600 nm that curve is steep and read off a graph: lasers 1 and 2 may be
  10 % off on it.

The caption says which response a map rests on and how much the power
moved between before and after. A map made without power readings (a
run before 0.7.6, or a laser placed from `machine.toml`) has no EQE: its
panel is blank and says so.

## How long a folder takes to open

Every map is built again from its file, from the alignment saved beside
it. `20261106T163140Z_full_test` (three lasers, 18 x 20 mm, 120 MB a
file) opens in about 10 s on the PC, 3 s a laser, 1.3 s of it reading
the file. A laser with no alignment saved yet (a run made before 0.7.4,
or a file changed since) is searched for first: about 20 s more for a
map that size, once. The window stays usable while a folder loads, and
the footer says which file it is reading and, at the end, how many
maps came from saved alignments.
