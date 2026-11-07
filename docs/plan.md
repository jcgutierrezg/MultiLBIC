---
type: state
title: "Plan"
---

# Plan

Phases, what "done" means for each, and what is open. What happened in
each push is in [`CHANGELOG.md`](../CHANGELOG.md); decisions are in
[decisions](decisions.md).

| | |
|---|---|
| status | Phases 0–6 merged. **Phase 7 (the viewer and spectral response) planned**, branch `phase-7-viewer`. |
| next | Step 4: lasers compared. Steps 2-3 (a run folder as one set of maps, the viewer with one map) are done. |

## Phases

| Phase | Done when | Outcome |
|---|---|---|
| 0: foundations | `uv sync && uv run pytest` passes in CI and a fresh clone installs on the Pi | PR #1, 0.1.0 |
| 1–2: probes, devices and simulators | every device runs in simulation in CI and on the machine from a script | PR #2, 0.1.11; laser firmware 2.0.0; [hardware](hardware.md) from the first bench sessions |
| 3: scan core | a simulated scan recovers the synthetic sample within tolerance despite 5 ms latency, 20 µm backlash and a 100 ppm clock | PR #3, 0.2.1 ([scan](scan.md#the-simulated-scan)) |
| 4: runs from the command line | a real map comes off the machine without the window | PR #5, 0.4.13: `calibrate`, `run` ([run](run.md)) |
| 5: the window | a full run driven from the window, which also works on the simulator on Windows | PR #6, 0.5.15 ([gui](gui.md)) |
| current ranges per sample | a mixed-range run of lasers 1–3 completes, and a clipping laser steps up | PR #7, 0.5.27 (D25–D27) |
| 6: commissioning | maps from all six lasers line up, and the sync error is measured | PR #8, 0.6.55 ([commissioning](commissioning.md), [timing](hardware/timing.md)): lasers within 39 µm along u and 29 µm along v, `L` = 15 ms, D28–D29 |
| 7: the viewer and spectral response | a real six-laser run, with power read before and after each map, opens in `multilbic view` on the PC and on the Pi, as current and as EQE, with a spectrum at any pixel | below |
| later | | below |

## Phase 7: the viewer and spectral response

One branch, `phase-7-viewer`; one bench session at the end, then one PR.
Decisions D30–D33.

**What it gives.** A run's maps compared across wavelengths: each laser's
map as photocurrent or as EQE, the lasers side by side on one grid, the
ratio of any two, and the six-point spectrum at a pixel or over an area.

**The viewer** (D30) is its own window, `multilbic view [FOLDER]`, on
the same Tk look as `multilbic gui`. It runs on the PC and on the Pi and
opens a run folder wherever it is: folders are copied from the Pi by
hand (USB stick or `scp`). It reads files only: no devices, no lock.

**Power** (D31). The laser warms up on the photodiode, where it was just
located, and the end of the warm-up is its power before the map. After
the map the stage goes back to the open quarter for a second reading.
EQE divides each row by the power at that row's time, interpolated
between the two readings.

**EQE** (D32). EQE of the cell = EQE of the photodiode × cell current ÷
photodiode current, both lit by the same beam. The photodiode's EQE at
each wavelength comes from the S1223-01's typical responsivity curve in
Hamamatsu's datasheet, so the viewer labels it "EQE (datasheet
photodiode)". A calibrated photodiode later makes it absolute with only
its curve changed.

Already in place: the line-up's offsets are applied when the stage
places each map, so a run's lasers share u and v and the viewer shifts
nothing. Runs made before Phase 7 have no power readings and open as
current only.

Steps:

1. **The plan** (0.7.0): this section and D30–D33.
2. **A run folder as one set of maps** (`store/runfolder.py`, done
   0.7.1): every laser's map rebuilt from its file (`scan.mapping`) and
   put on one shared u, v grid; the run's lasers, wavelengths, ranges and
   calibration from the headers. Clipped attempts are listed, unreadable
   files reported, a run still going opens. Two real six-laser runs open
   in about 1.3 s each.
3. **The viewer, one map** (done 0.7.3, [viewer](viewer.md)): open a
   folder, pick a laser; the map drawn as the window draws it
   (`store/image.draw_map`, `[display]`), colour limits, the value under
   the cursor, a line profile along a drawn line that stays when the
   laser changes. Each laser's alignment is saved beside its file, by
   the run and the viewer (D30 revised, 0.7.4): a full-size three-laser
   run opens in about 10 s on the PC instead of 80; **Re-align** and
   **Set shift** change it.
4. **Lasers compared**: all of a run's lasers side by side on the shared
   grid with one colour scale or each its own; the ratio of any two.
5. **Power in runs** (simulator first): the laser-off baseline taken at
   the sample before the laser is located, so the laser stays lit from
   its warm-up to the end of its map; the warm-up on the photodiode,
   channel 2 recorded as the warm-up row; the power before (the end of
   the warm-up) and after (back on the open quarter) in the file's
   header and trailer; the extra time in the estimate and the Plan tab.
   A failed power reading leaves the map without EQE, never stops the
   run. The simulator's photodiode drifts on request, so the test can
   check the interpolation.
6. **EQE**: the S1223-01's typical curve in the repository with its
   source; EQE per pixel from the power interpolated in time; the
   viewer switches any map, the comparison and the ratio between current
   and EQE, and shows each map's power drift.
7. **The spectrum**: click a pixel or drag an area, and the EQE at the
   six wavelengths (444–848 nm) is plotted, with the spread over the
   area.
8. **Docs** (`docs/viewer.md`; run file and run order in `scan.md` and
   `run.md`) and **the viewer on the Pi's screen** (fonts, speed).
9. **Bench**: a six-laser run on a cell with the power readings (ask
   before motion and lasers); the drift between readings, laser 2's
   included; EQE below 1 everywhere and a plausible spectrum for the
   cell; the run opened on the PC and on the Pi. Then the PR.

What to watch:

- The datasheet curve is typical: this photodiode may differ from it by
  some percent, more at 444 and 848 nm.
- Laser 2 is weak and fading, so its EQE is the noisiest.
- At 1.3–2.0 mA with small spots, the cell or the photodiode may not be
  linear ([photodiode](hardware/photodiode.md#readings)); that would bend
  EQE for the bright lasers.

## Later

- **Tiling** samples larger than AB's range with XY.
- **The viewer's exports**: figures and gridded maps as CSV or TIFF.
- **Laser health**: each run's power readings logged run after run.
- **Laser 2 is weak and fading** (−47 to −9 µA on the photodiode over a
  week): its supply (lasers 1 and 2 are starved by the 5 V LM317) or its
  cable ([lasers](hardware/lasers.md#the-laser-supply)). A hardware fix.
- **Better offsets**: average several line-ups rather than taking one.
- **Save to Marlin's EEPROM** the 5 mm/s ceiling and A's StallGuard
  threshold of 135, with the home offset put back to 0 first.
- **A plain error when a device's port is missing**, instead of a
  traceback.
- A proper dark enclosure, and with it D8 (slow drift).
- Pi polish: udev rules in the repository, a desktop launcher; the
  Zensical docs site.
- Someday: the TFT35 as a jog pendant (until then, covered during maps).
  Option C (the hardware row marker) is dropped (D33).
