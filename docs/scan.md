---
type: reference
title: "Scan"
---

# Scan

How a map is made from a run, as built in Phase 3. The design it
follows is in [architecture](architecture.md#position-sync); decisions
are in [plan](plan.md#decisions).

| Module | Job |
|---|---|
| `multilbic/scan/geometry.py` | The sample frame: `a = origin_a + u`, `b = origin_b + v`, no rotation |
| `multilbic/scan/raster.py` | The row plan: rows, run-up, stream rate, bounds, time estimate |
| `multilbic/scan/timing.py` | The motion model, the clock map, row anchors |
| `multilbic/scan/alignment.py` | The serpentine shift, measured from the data |
| `multilbic/scan/binning.py` | Dark baseline, mains removal, the pixel grid |
| `multilbic/scan/mapping.py` | The whole chain, from a run's raw record to a map |
| `multilbic/store/runfile.py` | The run file: writer and reader |
| `multilbic/store/image.py` | A map as a PNG |
| `multilbic/run/rows.py` | One laser's map on the devices, written as it goes |
| `multilbic/sim/rig.py`, `sample.py`, `scan.py` | The simulated machine, the synthetic sample, the headless scan |

`scan/` does no I/O, so all of the maths is tested without devices.

## The row plan

- Row `k` is at `v = (k + 0.5) × pitch`, the centre of pixel row `k`.
- Each row is one `G1` along A from a run-up before the sample to a
  run-out after it. The run-up is the acceleration distance plus
  0.05 mm, at least 0.1 mm: at 5 mm/s that is 0.3 mm.
- Serpentine by default (D3); one direction returns A between rows.
- **Stream rate** (D2): 2 samples per pixel at the scan speed, kept
  between 200 Hz (below that 50 Hz is too coarsely sampled to remove)
  and 1000 Hz (the Pi's reader kept up to ~1190/s). A pixel too small
  for the speed is refused with the speed that would work.
- Refused before anything moves: a speed over `[ab] max_feed_mm_s`, a
  pitch below one microstep, and any row outside the AB safe range.

## Position

**Row anchors.** A row ends when Marlin's `ok` to the `M400` after it
arrives; the start is that time minus the modelled duration. The start
of the move is not used: the first-move delay was 113–135 ms on the
bench, a 40 µm spread at 2 mm/s. Marlin's `Reply` now carries `sent_s`
and `received_s`, stamped on the reader thread.

Between rows, the B step gets its own `M400`, so each row starts from
rest. Queued back to back, Marlin would carry speed through the corner
and the row would no longer be the trapezoid the model assumes.

**The motion model** (`timing.Trapezoid`) is written separately from
the simulator's (`sim/motion.py`). A test checks the two agree on 50
random moves, and that the model reproduces the bench's speed-trial
table.

**The clock map.** Each sample's `host arrival − device stamp` is at
least the true offset. The smallest in each 1 s window is kept, and the
map is the lower edge of those minima: the line along their lower
convex hull that lies closest to them. A window where the host read
late sits above the line and does not tilt it, as it would a
least-squares fit. It is updated as samples arrive (`ClockTracker`).

**The serpentine shift.** Everything left is constant: the `ok`'s
latency, the stream's smallest delay, backlash on A. Each puts forward
rows one way and reverse rows the other. The shift is measured by
cross-correlating the A-derivative of neighbouring rows (on a 0.5 µm
grid, smoothed over 2 µm), median over pairs, and half of it is taken
off each direction. Rows with no edges crossing them give a weak
correlation; then the shift is reported as not found and nothing is
corrected. The shift and its quality go into the run's trailer.

**B backlash** is not seen by the alignment, since rows always step
+B. The first row is approached from below so the slack is taken up
the same way for every row; the stage then sits half the backlash
behind B's commanded value throughout. Corner calibration (Phase 4)
has to approach the corner the same way, and then the offset cancels.

## Cleaning

- **Dark baseline.** Each laser's map starts with the laser off and the
  stage still (2–3 s). Its mean is subtracted from every sample, its
  spread after mains removal is the noise floor. Both go in the trailer.
- **Mains.** Pixels last a few ms, too short to average whole 20 ms
  cycles, so each row has the best-fitting sines at `mains_hz`
  (`machine.toml`, 50 Hz) and two harmonics subtracted. A large step in
  the map leaks about 1 % into those sines over a 30-cycle row.
- **Slow drift** is left in. How to separate it is decision D8, set
  aside while there is no enclosure. On the simulated map it shows as
  the gaps between cells sitting tens of nA off zero.

## The run file

One CSV per laser map, in SMUniversal's `#`-header style, so that
`pandas.read_csv(path, comment="#")` gives the plain sample table:

```text
# MultiLBIC run
# schema: multilbic-run/1
# sample: ...            one `# key: value` per line; values are JSON
# status: incomplete
row,direction,channel,device_ms,host_s,current_a,voltage_v,a_mm,b_mm
-1,0,1,...                the dark baseline
#row: {"index": 0, "b_mm": ..., "end_s": ...}
0,1,1,...                 that row's samples
...
# status: complete        the trailer: status, clock map, samples
```

- **Appended and flushed after every row** (D1). Nothing is rewritten:
  what is known only at the end goes in the trailer, and the reader
  lets a later key override an earlier one. A file whose last status is
  `incomplete` was cut short, and every row in it is still readable.
- **Raw first.** `device_ms` (the instrument's stamp) and `host_s` (its
  arrival) are kept for every sample, and each row's anchor, so a map
  is always rebuilt from scratch (`scan.mapping.build_map`). `a_mm` and
  `b_mm` are only the positions as mapped when the row was written,
  before alignment, for a quick look.
- **One line per packet**, with a channel column: the two channels
  stream separate packets, so they are not paired up.
- The header names the sample, laser and wavelength, frame, pixel,
  pitch, speed, stream rate, mains frequency, app version, commit and
  dirty state, and every device's firmware.

## The simulated scan

```bash
uv run python -m multilbic.sim.scan --height 0.4 --speedup 2
```

It builds the simulated machine with the Phase 3 faults, homes it, scans
one laser's map into a run file in `runs/` (ignored by git), rebuilds
the map from that file alone, saves a PNG next to it, and prints how far
the result is from the truth.

**The faults** (`sim.rig.Faults`, the agreed case of 2026-10-20):

| Fault | Value |
|---|---|
| Latency on Marlin's replies | 5 ms, plus 0–1 ms at random |
| Backlash, A and B | 20 µm (the stage trails the motor through a dead band) |
| SMU clock | 100 ppm fast, 123 s off the host's, rate 1 % off what was asked |
| SMU delivery | in bursts every 100 ms, as the bench saw above 500 Hz |
| Noise | 20 nA white, 20 nA mains (50 Hz + 150 Hz), 40 nA RMS drift at 0.2–0.7 Hz |

**The sample** (`sim.sample.SyntheticSample.default`): two cells with
different spectra, two fingers across each (sharp A edges every row
crosses), and a defect losing 60 % of the second cell's current. The
spot is a Gaussian (σ = 5 µm); the current under it is exact (error
functions), so every edge's half-way point is exactly where the edge is.

**The truth.** The simulator keeps the stage's whole path and can invert
any stamp to the time it was taken, so each sample's mapped position is
checked against where the stage really was.

**Results** (1 × 0.4 mm, 5 µm pixels, 50 µm pitch, 1 mm/s, 400 Hz, at
2× real time; `tests/test_sim_scan.py` asserts the tolerances):

| Check | Tolerance | Result |
|---|---|---|
| A edges (14, 3 flat rows each) | 5 µm (max of 5 µm and one pixel) | worst 3.8 µm |
| B edges (3, interpolated between rows) | 50 µm (one pitch) | worst 9.4 µm |
| Shift measured vs present | 2 µm | 9.93 vs 9.68 µm |
| Every sample on the sample vs the true stage | 5 µm | worst 0.52 µm |

The shift present is 20 µm of backlash minus twice the 5.5 ms latency at
1 mm/s, so 9 µm, plus a fraction of a millisecond the simulator's own
threads add.

**Why 2× and precise sleeps.** A real sleep overshoots by about 0.5 ms
on Windows, and the speed-up multiplies it: at 20× a reply arrives 10 ms
of simulated time late, which shows up as latency nobody injected. The
measured shift then still matches the shift present to 0.3 µm, so the
alignment is right, but the shift present no longer matches the faults.
`ScaledClock(precise=True)` sleeps short and yields until the exact
moment; device tests keep the plain one.

**What the map looks like:** the left cell brighter than the right
under laser 3 (652 nm), dark fingers, the defect as a dimmer block in
the right cell's upper half, and the rows outside the cells near zero
give or take the drift.

## Not done here

Phase 4: homing and corner calibration as steps of a run, the loop over
lasers, Stop, fault handling beyond "laser off, stream stopped, output
off, file marked", and running a real map off the machine.
