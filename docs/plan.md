---
type: state
title: "Plan"
---

# Plan

Phases, what "done" means for each, and the decisions still open. Short
by design: what happened in each phase goes in
[`CHANGELOG.md`](../CHANGELOG.md), not here.

| | |
|---|---|
| status | Phases 0 to 5 merged (Phase 5 as PR #6, 0.5.15). **Current ranges per sample** planned (0.5.16, branch `current-ranges`, 2026-10-27), before Phase 6 goes on: a run with lasers 100x apart in brightness needs a range per laser. Phase 6 is planned on its own branch (`phase-6-commissioning`, 0.6.1) and waits for this. |
| next | The current-ranges PR: bench step 6 passed (0.5.23, [bench](bench.md#current-ranges-the-bench)). Then Phase 6 again. |

## Phases

### Phase 0: foundations (no machine needed)

- `git init`, GitHub repo, uv project, `pyproject.toml`, pinned
  SMUniversal dependency, ruff + mypy (boundaries only) + pytest, CI on
  Ubuntu and Windows.
- `machine.toml` holding today's known values (laser centres, servo
  angles, AB range, feeds).
- Pinned SMUniversal dependency with the unused instrument libraries
  dropped through uv overrides, plus the import guard test (see
  [architecture](architecture.md#what-comes-from-smuniversal)).
- Confirm that Python 3.14 + Tk (uv-managed) and the reduced dependency
  set install and run on the Pi.
- Docs split by topic, plus the changelog.

**Done when** `uv sync && uv run pytest` passes in CI and a fresh clone
installs on the Pi.

### Phase 1: bench probes (on the Pi, over SSH)

Small scripts in `tools/`, independent of the app. Their output goes into
[hardware](hardware.md).

- **Marlin:** `M503` dump (the actual EEPROM values), real A/B speed
  limit at 2–5 mm/s, first-move delay, `M400` and `ok` latency, how
  `M410` behaves mid-row.
- **Laser board (current firmware):** switching and settle times, reply
  text.
- **miniSMU, after upgrading to firmware 1.5+:**
  - achieved stream rate at 100–1000 Hz, one and two channels;
  - timestamp resolution and jitter, clock drift against the host;
  - noise floor and offset at 0 V, open circuit and with a contacted
    cell, lights on and off;
  - range switching while streaming.

**Done when** the sync error budget can be checked against measured
numbers, and the stream rate and A/B speed are chosen.

**First session, 2026-10-19 (no motion, no lasers):** every device
answers on the Pi; findings are in [hardware](hardware.md). It found the
EEPROM running settings (A/B at 6 mm/s), the streaming limits (bulk
reads needed above a few hundred Hz on the Pi; the device's rate is not
the requested one), and a two-channel stop bug, now fixed. Still owed:
the motion, speed and laser steps (at the machine), and the miniSMU
probe with a stated load.

**State (0.1.8):** the probes are written and tested against the
simulators (`multilbic/bench/`). The runbook is [bench](bench.md).
Nothing has run on the machine yet.

### Phase 2: device layer and fakes

- Marlin client, laser driver, SMU streaming wrapper. Each one is tested
  against its fake over the same protocol.
- New laser firmware: reply protocol, state query, settle time you can
  set, no park on `LASER 0`.
- Tests marked `hardware` re-run the same checks on the Pi.

**Done when** every device runs in simulation in CI and on the real
machine from a script.

**State (0.1.1):** drivers, simulators and the check script
(`python -m multilbic.hardware.check`) work in simulation. Still owed:
compile and flash laser firmware 2.0.0, then `--real` and
`pytest --hardware` on the Pi.

### Phase 3: scan core

- Geometry, raster plan, timing and clock mapping, binning, serpentine
  alignment, run file writer and reader.
- A headless scan in simulation of the synthetic sample: writes a run
  file and a PNG.

**Done when** the simulated scan recovers the synthetic pattern within
tolerance despite injected latency, backlash and clock drift.

The test case, agreed 2026-10-20: 5 ms reply latency, 20 µm backlash on
A and B, the SMU clock 100 ppm fast. Edges within 5 µm or one pixel,
whichever is larger; the forward/reverse shift estimated within 2 µm of
the one present.

**State (0.2.0): done in simulation.** Worst A edge 3.8 µm, worst B
edge 9.4 µm (pitch 50 µm), shift 9.93 µm measured against 9.68 µm
present, every on-sample position within 0.52 µm of the true stage
([scan](scan.md#the-simulated-scan)). Slow drift is left in the map
(D8).

### Phase 4: run orchestration and command line

- Home → corner calibration → per-laser loop → rows.
- Stop and fault handling, incremental writing, event log.
- A command-line run of the real machine on a test target.

**Done when** a real map comes off the machine without the GUI.

Agreed 2026-10-20 (D11–D14 below): XY-based placement as in the old
script; one corner, typed size and a laser trace of the outline;
`calibrate` and `run` as separate commands; the first target a
contacted solar cell with fingers. The bench session is
[bench](bench.md#phase-4-first-maps).

**State (0.4.0): built and tested in simulation.** `multilbic
calibrate` and `multilbic run` ([run](run.md)); XY placement with
swapped and reversed axes, Stop mid-run and three injected faults all
tested against the simulators. Bench: axis directions checked 2026-10-21 (X along +A, Y
along +B; the calibration corner is the sample's top-right as seen at
the machine). Steps 2-6 done 2026-10-21 to 2026-10-23: first real maps,
the forward/reverse shift at two speeds (an 18.6 ms stamp lag), Stop
([hardware](hardware.md#first-maps-2026-10-21-to-2026-10-23)). Step 7
done 2026-10-23: three lasers on one edge, registered to within about
0.3 mm. **Phase 4 is done.**

### Phase 5: GUI

- A Tk window replacing the old one: connection, jog (XY/AB, step size,
  motors on/off), sample setup, calibration steps with a perimeter
  preview, laser select, live heatmap, console, progress and time
  estimate.
- End-of-run plot.

**Done when** a full run is driven from the window, and the window
works against the simulator on Windows.

Agreed 2026-10-26 (D6, D17–D20 below): `multilbic gui [--sim]`, laid
out for 1920×1080. One worker thread owns the devices; the window sends
it commands and reads its events through queues (SMUniversal rule 8).
From SMUniversal: theme, console window, tooltips, widgets, progress
maths, single-instance and thread guards; not `base_app` or
`connection_panel`. The window, left to right: machine (connection,
jog, laser and live photocurrent), sample (calibration in three steps
with an outline preview, run setup with the plan and estimate updating
as you type), run (live map per laser, progress, Start/Stop, the
corrected map at the end, "Open run file…"). Compare with the old
window once built.

Steps, each push a 0.5.x:

1. Branch and this plan.
2. Refactor, command line unchanged: a `Calibrator` that does the
   calibration actions, with the text prompt on top of it; an `on_row`
   hook in `scan_laser` and `Session` that hands each finished row out.
3. The worker and controller, no Tk: commands in, events out, states
   (disconnected, idle, calibrating, running, stopping), tested against
   the simulator with its injected faults.
4. The window: connection, jog, laser, position, console, Stop.
5. Calibration panel with the outline preview; run setup with the plan
   and estimate.
6. Live map, progress, the end-of-run map. Window tests in CI (`xvfb` on
   Ubuntu), a full simulated run driven through the window with the
   thread guard on.
7. **On the Pi, no motion, no lasers:** the simulated GUI on the Pi's
   monitor, started there by the operator. Does it fit, does Tk 9 draw
   it right, does a Pi 4 keep up with the live map.
8. Docs (`docs/gui.md`) and the changelog.
9. **Bench:** a short laser 2 map on the test cell, calibrated and run
   from the window; Stop mid-row from the button; closing the window
   mid-run. Then the PR.

Until step 7 nothing needs the Pi.

**State (0.5.11): Phase 5 is done.** Steps 1-6 in simulation on Windows;
step 7 on the Pi's monitor, which led to D21 (smooth text); step 8 the
docs; step 9 on the machine, 2026-10-26 and 27: a real map from the
window, STOP, Esc and closing mid-run all passed. Also added on the way:
laser colours and SMUniversal-style accents.

### Current ranges per sample

Found 2026-10-27 setting up a three-laser run: on the test cell lasers 1
and 3 give 60-80 uA and need the 650 uA range, laser 2 gives 0.7 uA and
needs 25 uA to stay clear of the noise, and a run had one range for all
(D15), so a mixed run either stops on laser 1's first row or buries
laser 2. The photocurrent depends on the sample (its response at each
wavelength, contacts, area, bias) as much as on the laser, so the range
is chosen per laser and per sample. Agreed 2026-10-27: D15 revised,
D25-D27 below. Phase 6 waits for this (its D22-D24 are on its branch).

- **Ranges:** the miniSMU's five, 1 uA, 25 uA, 650 uA, 15 mA and 180 mA
  (`docs/hardware.md`; the code's list stopped at 15 mA). The SMU's
  current limit follows the range, at its full scale: it was fixed at
  1 mA, which made 15 mA and 180 mA unusable. At 0 V the cell's
  photocurrent decides the current; with a forward bias the limit only
  grows when a laser has stepped up.
- **Check ranges** (calibration's step 4): for each laser ticked in Run
  setup, XY places the sample as the run will for it, the laser comes
  on, and the stage runs a coarse grid over the sample, 3 lines along A
  and 3 along B at 1/6, 1/2 and 5/6, at 2 mm/s, while single readings
  are taken on autorange as fast as the SMU answers (not the stream:
  autoranging costs nothing there). The check uses Run setup's bias.
  The range is the smallest that holds **3x** the brightest reading
  (laser 2's output doubles in its first two minutes). As a safety net
  a brightest reading at 0.8-1.1 of a range's top has the grid read
  again with the next range up fixed, and the one after while that
  clips. The time is
  shown before it starts (about 15 s a laser on a 2 mm sample, 1.5 min
  on 20 mm). It ends with the reference laser back on the corner; STOP
  works throughout. In the window a button, in `calibrate` a `ranges`
  command.
- **Saved with the calibration:** per laser, the range, the brightest
  reading and when; old calibration files load as unchecked.
- **Run setup:** a range per ticked laser, from the check ("checked") or
  else the one range for all ("not checked"); the Plan tab lists them.
  `run --current-range` takes one range or one per laser
  (`1=650u,2=25u,3=650u`); without it `run` uses the calibration's.
- **At Start:** if a ticked laser's range is not checked for this
  sample, the dialog offers Check ranges first, Start anyway, Cancel.
- **The step-up:** a row or baseline that reaches the end of its range
  stops that laser; its attempt is kept as `laserN_<nm>nm_<range>.csv`,
  status `clipped`, and the laser's whole map starts again one range up,
  with a fresh baseline and no second warm-up. The window says so.
  Clipping at 180 mA fails the run. On by default; `--no-step-up` and a
  box in the window turn it off.
- **Default speed 4 mm/s** (was 2): bench-proven on this machine
  (2026-10-23 maps, the alignment agreeing with the edge), and about
  40 % shorter runs. 5 mm/s waits for Phase 6 step 3.

Steps, each push a 0.5.x:

1. Branch, this plan, D15 revised, D25-D27; the default speed.
2. A range per laser through the run (request, file headers, `run.json`,
   `run --current-range` per laser), 180 mA, the current limit
   following the range. Simulation: a three-laser run with mixed ranges.
3. The step-up. Simulation: the synthetic cell bright enough to clip
   laser 1 at 25 uA, and the run still completes.
4. Check ranges: the grid in the `Calibrator`, the worker, `calibrate`'s
   `ranges`, saved and loaded. Simulation tests.
5. The window: Calibration step 4, per-laser ranges in Run setup, the
   Plan tab, the offer at Start, the step-up shown. Window tests,
   screenshots, the Pi's screen.
6. **Bench** on the test cell: check lasers 1-3 (expect 650 uA, 25 uA,
   650 uA), a three-laser run with them, then laser 1 forced to 25 uA to
   see it step up and finish. Also the first real use of a current
   limit as low as the 1 uA and 25 uA ranges (it was always 1 mA):
   check the SMU accepts it. Then the PR. **Done 2026-10-27**: 650u, 25u, 650u;
   the run complete; laser 1 stepped up from 25u and completed. Open:
   laser 1 read 4x brighter after the run's warm-up than in the check
   ([hardware](hardware.md#current-ranges-on-the-test-cell-2026-10-27)).
   Not warm-up and not autorange: laser 1 relit within about 1.5 s of
   going off comes back at 40 % and stays there. 0.5.25: the laser
   driver keeps each laser dark for `relight_ms` (3 s) before relighting
   it.

### Phase 6: commissioning

- Install the channel-2 photodiode on an AB corner. Use it to find
  every laser's centre (6 included) and to knife-edge each spot size.
- Repeat the A/B speed test.
- Validate continuous scanning against step-and-measure on a patch.
- Decide whether option C (hardware marker) is needed.
- Ground the flat on the A/B shafts.

**Done when** maps from all six lasers line up, and the sync error is
measured and recorded.

### Phase 7: later

The viewer app (heatmaps, comparing wavelengths), the TFT35 jog pendant,
option C if needed, spectral-response maps normalised by the
photodiode, tiling samples
larger than 35 mm with XY, Pi deployment polish (udev rules in the repo,
desktop launcher), and the Zensical docs site.

## Decisions

| # | Decision | Agreed |
|---|---|---|
| D1 | When the run file is written | After every completed row; Stop keeps the partial data (unlike SMUniversal rules 3 and 7). |
| D2 | Stream rate | Derived from the requested pixel size, usually the smallest. Compression is decided later, once real files exist. |
| D3 | Row order | Serpentine by default, one direction as an option. |
| D4 | Starting version | 0.1.0, under MAJOR.SESSION.PUSH. |
| D5 | Channel-2 photodiode | On an AB corner. What it gives is in [architecture](architecture.md#the-channel-2-reference-photodiode). |
| D6 | How the GUI on the Pi is reached during development | **Not remotely** (2026-10-26): it is built and tested against the simulator on Windows, and on the Pi it runs on the Pi's own monitor, started there by the operator. Over SSH only logs and run files are read; no remote desktop or X forwarding over the hotspot. |
| D7 | SMUniversal dependency | Pinned git dependency, installing only what the miniSMU needs. |
| D9 | A/B speed ceiling in `machine.toml` | **6 mm/s**: matches the board's EEPROM; A and B both reached 3–6 mm/s with no missed steps (2026-10-20). A and B share it, being mechanically identical. B was noisier and vibrated more at 6 mm/s, so **scans should use 5 mm/s or less**. The scan speed is chosen per run in Phase 3. |
| D10 | Laser settle time | **2000 ms**, in `machine.toml` (`[laser_board] settle_ms`), applied by the driver at every `open()` because the firmware forgets a runtime value on power-up. 1000 ms was stable on the worst swing and 500 ms was not; 2000 ms keeps a wide margin and costs only seconds per run. |
| D11 | Where the sample is | XY-based, as the old script: the corner is jogged under the reference laser (2) with AB centred; for each laser XY centres the sample and AB rasters around the AB centre. Axis directions and the reference laser in `machine.toml` `[geometry]`. Every placing move ends moving up. |
| D12 | Corner calibration | One corner (the one the sample extends from towards +A and +B), the size typed, and the laser tracing the outline to check it. |
| D13 | Command line | `multilbic calibrate` (interactive, saves a file) and `multilbic run` (reads it, needs no terminal, so it survives SSH drops under `nohup`). `run` homes first. Ctrl+C or SIGINT/SIGTERM is Stop. No resume within a laser. |
| D14 | Lasers with placeholder positions | Refused by `run` unless `--allow-unmeasured`. |
| D15 | SMU range during scans | Fixed for each laser's whole map: autoranging drops 10-15 ms of samples at every switch. **Revised 2026-10-27: per laser and per sample** (was one range per run, default 25 uA): on the test cell lasers 1 and 3 need 650 uA and laser 2 25 uA. See D25-D26. |
| D16 | Laser warm-up | Each laser stays on with the stage still for `--warmup` (default 60 s) before its first row, recorded in the file: laser 2 drifted 2x after switch-on. |
| D17 | Where a GUI run lives | In the window's process, on the worker thread (2026-10-26). A crash of the window stops the run as Stop does and keeps the file; a run that must outlive the window is `multilbic run` under `nohup`. The single-instance guard keeps a GUI and a command-line run from opening the same ports. |
| D18 | The live map | Binned row by row as rows finish, **without** the forward/reverse correction; the corrected map, built from the file as the PNG is, replaces it when each laser ends. To be looked at again after the first real runs (2026-10-26). |
| D19 | Jog keys | Arrows, plus the command line's `w a s d q e`, and only while the jog panel has focus, so a stray key can't move the stage (2026-10-26). |
| D20 | Start | A confirm dialog with the lasers, the plan and the estimate, as `run` asks on the command line (2026-10-26). |
| D25 | Where a sample's ranges come from | **Measured at calibration and saved with it** (2026-10-27): "Check ranges" runs a coarse grid (3 lines along A, 3 along B) under each laser on autorange and picks the smallest range holding 3x the brightest reading. Editable in Run setup; Start offers the check for unchecked lasers. The SMU's current limit follows the range's full scale; all five ranges, up to 180 mA. |
| D26 | A range that clips during a run | **Step up and start that laser's map again** (2026-10-27), keeping the clipped attempt in its own file; clipping at 180 mA fails the run. On by default, can be turned off. |
| D27 | Default scan speed | **4 mm/s** (2026-10-27; was 2): bench maps at 4 mm/s were good and the alignment held; runs are ~40 % shorter. 5 mm/s after Phase 6 step 3 checks it. |
| D21 | Python on the Pi | **Deadsnakes' `python3.14` + `python3.14-tk`** (2026-10-26), with Ubuntu's Tk 8.6. uv's own 3.14 has Tk 9.0 built without Xft, so the window's text was jagged (step 7 of Phase 5); Ubuntu's Tk is built with Xft. `deploy/pi/setup.sh` prefers it and falls back to uv's with a warning. CI keeps a uv-managed aarch64 job: the code is the same. |
| D8 | How LBIC signal is separated from slow drift and mains (dark noise is mostly 0.2–0.7 Hz drift, the band map features occupy at 2 mm/s; see [hardware](hardware.md#streaming-measured-2026-10-19)) | Open, **set aside** (2026-10-20): no enclosure for now. (a) A stable dark enclosure, plus laser-off baselines per row. (b) Chop the laser from the Xiao at a few hundred Hz and demodulate in software (lock-in), with the reference from channel 2 or the Xiao's timing. (b) is the more robust; (a) is needed anyway. Note for (b): the miniSMU tops out near 1.4 kHz and the Pi's reader near 1.2 kHz, so chopping is limited to the low end. Phase 3 does the mains removal and a dark baseline per map; drift would be removed in the per-row cleaning in `scan/binning.py`. |
