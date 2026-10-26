---
type: reference
title: "Architecture"
---

# Architecture

This is the design agreed before any code was written. Decisions are
recorded in [plan](plan.md#decisions). The device layer (Phase 2), the
scan core (Phase 3) and command-line runs (Phase 4) are built; where the
build differs from what follows, the difference is noted here and the
detail is in [devices](devices.md), [scan](scan.md) and [run](run.md).
*As built,* placing the sample uses XY as well as AB (D11), and the
command line is `multilbic calibrate` and `multilbic run` (D13).

## Goals

1. **Testable without the machine.** Every device has a simulator that
   speaks the same protocol as the real thing. A full scan runs on
   Windows or in CI and produces a map you can check by eye.
2. **Easy to pick up again.** Small modules with one job each, and docs
   split by topic rather than one long README.
3. **Correct position for every sample.** Syncing measurements to stage
   position is the central technical problem, so it gets its own module
   and its own tests.

## Layers

```
gui/  ──►  run/  ──►  scan/        (pure: geometry, raster, timing, binning)
             │
             └──►  hardware/  ──►  transports  (serial; miniSMU via SMUniversal)
                       ▲
                     sim/          (fakes for every device + synthetic sample)
```

Imports point one way only, as in SMUniversal. `scan/` imports nothing
with I/O, so all the maths behind a map is unit-testable. `gui/` never
talks to a device directly. It sends requests to `run/` and gets results
back through a queue (SMUniversal house rule 8, *the UI is a queue*).

### Package sketch

Flat layout, one namespace, matching SMUniversal:

| Module | Job |
|---|---|
| `multilbic/config/` | Load `machine.toml`: laser XY centres, servo angles, AB centre and safe range, feeds, ports per platform. Values you calibrate live in the file, not in the code. |
| `multilbic/hardware/marlin.py` | G-code client: line protocol, `ok`/`busy` handling, `ADVANCED_OK` buffer tracking, `M114` parsing, `M400`, Stop via `M410`, `M503` dump, homing, jog, motors on/off. |
| `multilbic/hardware/laser.py` | Laser board protocol: select a laser, all off, state query (once the new firmware lands). |
| `multilbic/hardware/smu.py` | SMUniversal's `UndalogicMiniSMU` for configuration and output control, plus a streaming reader that lives only here (streaming is not needed in SMUniversal). |
| `multilbic/scan/geometry.py` | Coordinate frames: machine XY, AB, sample frame, laser offsets, corner calibration. |
| `multilbic/scan/raster.py` | Row plan: row pitch, serpentine order, run-up/run-out, row count, time estimate, bounds checks against the AB safe range. |
| `multilbic/scan/timing.py` | Motion profile, SMU-clock ↔ host-clock mapping, per-row time anchors, sample → position. |
| `multilbic/scan/binning.py` | Raw samples → pixel grid, for the live heatmap and the end-of-run plot. |
| `multilbic/scan/alignment.py` | Estimate the forward/reverse row shift from data (the serpentine self-calibration). |
| `multilbic/run/` | The scan orchestrator in a worker thread: home → calibrate → per laser → rows; Stop and fault handling; incremental file writing. |
| `multilbic/store/` | The run file format: writer and reader, shared later by the viewer. |
| `multilbic/sim/` | Fake Marlin, fake laser board, fake streaming SMU, synthetic sample. |
| `multilbic/gui/` | Tk window: connection, jog, sample setup, laser select, calibration steps, live heatmap, console, progress and time estimate. *As built:* `gui/worker.py` (no Tk) is the thread that owns the devices; the window calls it and reads its events. Opening the machine, real (under the machine lock) or simulated, is `run/devices.py`, shared with the command line. |
| `tools/` | Bench probes, run on the Pi over SSH, independent of the app. |

### What comes from SMUniversal

A git dependency on `smuniversal-lab-suite`, pinned to a commit or tag.
What MultiLBIC imports:

- the miniSMU driver and its transport adapter (`UndalogicMiniSMU`,
  `BaseSMU`, `BaseInstrument`, the transport base, `limits`, `ranges`,
  `readback`);
- the `#`-header CSV convention and provenance (app version, commit,
  instrument firmware in every file);
- the event log, the thread guard and the single-instance guard;
- the Tk theme and generic widgets where they fit.

Not imported: experiments, the run store's keep-in-memory model, or
the plotter (the viewer is new: different experiment, different data).

**Only the miniSMU's dependencies come along.** SMUniversal installs
every instrument library by default (pyvisa, pyvisa-py, pyusb,
libusb-package, ni-gpib-usb-hs, plus scipy and pillow for its own
experiments). MultiLBIC needs none of them.

- **Why the code still works without them:** the modules listed above
  import only the standard library, `pyserial` and `minismu_py`, and
  SMUniversal's package `__init__` files are empty (checked 2026-10-18).
- **How we drop them:** MultiLBIC's `pyproject.toml` uses uv's
  `override-dependencies`, giving each unused package a marker that is
  never true. No change to SMUniversal is needed.
- **The guard:** a MultiLBIC test imports exactly the modules we use in
  that reduced environment. If a later SMUniversal release starts
  needing one of the dropped packages, updating the pin fails in CI
  instead of on the Pi.
- **Fallback, if overrides prove fragile:** move the shared modules into
  a small third package that both projects depend on. That is a bigger
  change, and it touches SMUniversal's drivers and their bench
  fingerprints, so it is not the first choice.

**Python 3.14** is SMUniversal's floor and becomes MultiLBIC's.
The Pi runs Ubuntu 24.04, which ships Python 3.12, so it gets a
uv-managed 3.14. *As built:* the Pi uses deadsnakes' 3.14 instead, whose
Tk draws smooth text (D21).
Phase 0 confirms that it runs there and that Tk works under it.

## Position sync

This is the problem the old script stopped at. During a row the stage
moves along A at constant speed while the SMU streams timestamped
samples. Each sample needs a position.

**Why it is manageable:** at 2 mm/s, **1 ms of timing error is 2 µm of
position error**. A few milliseconds of error stays below any plausible
spot size.

**Sources of error the old approach ignored:** acceleration, serial
latency, Marlin's 100 ms first-move delay, the SMU's clock being set
from the host only once, and lead-screw backlash on reversal.

### Option B, software only (the plan)

1. **Run-up and run-out.** Each row is queued as one motion sequence.
   It starts about 0.1 mm before the sample edge and ends about 0.1 mm
   after it, so acceleration (0.04 mm) and the first-move delay fall
   outside the measured span.
2. **Clock mapping.** Each streamed packet carries an SMU timestamp and
   has a host arrival time. The earliest-arriving packets bound the
   offset between the two clocks to about 1 ms. Tracking it through the
   run removes drift. `set_time()` is not relied on.
3. **Row anchors.** Each row's end comes from the host timestamp of the
   `ok` to the `M400` after it; the start is the end minus the modelled
   duration. Samples are put in host time through the clock mapping.
   *As built:* the start of the move is not used, because the first-move
   delay varies by about 20 ms on the bench, while the end is known to
   about a millisecond ([scan](scan.md#position)).
4. **Serpentine self-calibration** (serpentine is the default; scanning
   in one direction only is an option, D3). Any leftover constant delay, and
   backlash, shows up as a shift between forward and reverse rows.
   `alignment.py` measures it by cross-correlating neighbouring rows,
   corrects it, and writes it to the file header.
5. **Reference check.** A step-and-measure mode on a small patch
   (about 1×1 mm) gives positions with no timing involved. Continuous
   scans are validated against it during commissioning.

Raw SMU timestamps are always stored alongside the computed positions,
so a better calibration can re-map an old run without re-measuring.

### Option C, hardware marker (designed in, built only if B falls short)

- Wire a spare SKR pin to a free laser-board pin.
- Rebuild Marlin with its laser feature in inline mode, so the pin
  switches exactly when each measured `G1` starts and ends.
- The laser board gates the selected laser on that pin. The laser is
  then lit only during the measured span. That gives row edges in the
  SMU's own clock, plus a dark baseline every row.

The file format treats those edges as one more source of row anchors,
so nothing above `scan/timing.py` changes.

### The channel-2 reference photodiode

Mounted on a corner of the AB stage, outside the sample area (decided).
It sees a laser only when the stage parks that corner under the beam.
What it gives:

- **Comparable maps across wavelengths.** Photocurrent scales with
  laser power × the cell's quantum efficiency at that wavelength. The
  lasers' powers differ, so raw maps from two lasers can't be compared.
  Dividing by the photodiode current, corrected by the photodiode's
  published spectral responsivity, gives a relative spectral response
  per pixel. A calibrated photodiode would make it absolute EQE.
- **Drift during a map.** Measuring before and after each laser's map
  shows whether power changed during the scan. The map can be corrected
  linearly across rows, or flagged.
- **A pre-flight check.** A near-zero reading before a long scan means
  the wrong laser, a failed laser, or the servo didn't turn the barrel.
  Better to know before a 2 h map than after.
- **Laser positions, found automatically.** The photodiode is a fixed
  point on the AB stage. Scanning it under each laser finds that beam's
  position in machine coordinates. That fills in `LASER_POSITIONS`,
  including laser 6, which no card shows.
- **Spot size.** Scanning the photodiode's edge (or a razor blade over
  it) across the beam is a knife-edge measurement of each laser's spot.
- **Long-term laser health:** power per laser, logged run after run.

What it cannot give: continuous normalisation within a row, or row
edges for option C. Those would need a pickoff at the laser exit.

Requirements:

- a silicon photodiode (covers 444–848 nm), with an active area larger
  than the spot for the power readings;
- a cable to channel 2 with enough slack to move with the stage;
- a corner every laser can reach within XY + AB travel.

## Run time

Rows cost time; resolution along a row is nearly free. The table below
is for 2 mm/s. The A/B ceiling is now 6 mm/s (decision D9), which cuts
these times by up to 3×. The scan speed is chosen per run, trading speed
against samples per pixel, timestamp bunching and the drift band (D8):
at 6 mm/s a 1 mm feature passes at about 6 Hz, clear of the 0.2–0.7 Hz
drift. Along a row the
resolution is sample rate × speed (about 2 µm at 1 kHz and 2 mm/s).
Each extra row costs a full pass. Rough time per laser at 2 mm/s,
including turnarounds:

| Sample | 10 µm rows | 50 µm rows | 100 µm rows |
|---|---|---|---|
| 10 mm | ~1.5 h | ~18 min | ~9 min |
| 20 mm | ~5.8 h | ~70 min | ~35 min |
| 30 mm | ~13 h | ~2.6 h | ~1.3 h |

Row pitch can go down to one microstep (0.3125 µm), but the time
estimate is shown before Start. A pitch below the spot size is allowed
on purpose (oversampling).

## Run file

One CSV per run, using SMUniversal's convention:

- a `#` header block: sample, geometry, calibration, laser list,
  speeds, stream rate, clock mapping, alignment correction, app
  version, commit, firmware versions, completion status;
- then one row per raw sample: laser, row, direction, SMU timestamp,
  channel 1 current and voltage, channel 2 current, mapped X and Y.

*As built* ([scan](scan.md#the-run-file)): one file per laser, one line
per streamed packet with a channel column (the two channels stream
separate packets), and the host arrival time kept too. What is only
known at the end goes in a trailer of the same `#` lines rather than
rewriting the header.

Per-row anchors go in as `#row` comment lines, so
`pd.read_csv(path, comment="#")` still returns the plain sample table.

**Mains pickup** (measured, see
[hardware](hardware.md#streaming-measured-2026-10-19)): about 90 % of the
0 V noise on open leads is at 50 Hz. Raw samples are kept with their
timestamps, so the map can be cleaned afterwards with a notch at 50 Hz
and its harmonics along each row, or by averaging each pixel over whole
20 ms cycles. *As built:* a pixel lasts a few milliseconds, too short to
average whole cycles, so each row has the best-fitting mains sines
subtracted; `mains_hz` is in `machine.toml`.

**Drift is the harder problem** (measured with a contacted cell in the
dark: most of the noise is 0.2–0.7 Hz drift, where map features sit at
2 mm/s). Decision D8 in the plan weighs a stable enclosure with baselines
against chopping the laser and demodulating in software.

**A dark baseline in every scan.** A covered cell can't be measured
while contacted, and room conditions vary anyway. So each laser's map
starts with a few seconds of streaming with the laser off and the stage
still, written to the run file. That gives the offset to subtract and
the noise floor the map has to clear, under that run's real conditions
(room light, mains, cabling).

**The file is appended after every completed row** and flushed to disk
(D1). Until the run finishes, the header says `status: incomplete`, and
a trailer appended at the end says `complete`. A Stop or a crash leaves
every finished row readable.

**Size matters.** A 30×30 mm map at 10 µm rows with 1 kHz streaming is
tens of millions of samples, over 1 GB per laser. The stream rate is
derived from the requested pixel size (D2), and that pixel size will
usually be the smallest available, so files will be large. Compression
is deferred until real files exist to measure.

## Simulation

The fakes run the real driver code over an in-memory serial pair, so
the same protocol parsing is exercised in tests as on the machine.

- **Fake Marlin:** Marlin's move timing (trapezoid profile, 100 ms
  first-move delay, feedrate clamping, `busy`/`ok`, `M114`, `M400`,
  `M410`), plus injectable latency and backlash.
- **Fake laser board:** the current firmware's protocol first, the new
  one when it lands.
- **Fake SMU:** streams at the set rate with its own clock (offset,
  drift and jitter you can inject), reading current from the synthetic
  sample at the stage's simulated position.
- **Synthetic sample:** a recognisable pattern (cells, fingers, a
  defect, a known edge) with a response per wavelength.

**The key test:** a full simulated scan with injected latency, backlash
and clock drift must recover the pattern within a stated position
tolerance. The fake uses Marlin's motion model and the sync code uses
its own, so the test can catch a wrong model, not just confirm the code
agrees with itself. It passes; the numbers are in
[scan](scan.md#the-simulated-scan).

## Stop and faults

- **On Stop or a fault:** lasers off, Marlin quickstop (`M410`), SMU
  output off, motors stay energised. The partial file is kept and
  marked incomplete.
- **A lost device link** ends the run the same way, as far as the other
  devices allow, and is written to the event log.
- **The dark enclosure** is an interlock that warns; it never stops a run.

## Where this differs from SMUniversal

- **Saving.** SMUniversal never auto-saves (rule 3) and treats a run as
  a transaction (rule 7). Scans can last many hours, so MultiLBIC
  writes the file after every row, and Stop keeps the partial data
  (D1).
- **Dependencies.** Only the miniSMU's dependencies are installed, not
  SMUniversal's whole set.
- **Streaming** exists only here.
- **Motion** is a G-code device, not a measuring instrument. It sits
  under `hardware/`, and SMUniversal's driver registry does not apply.
