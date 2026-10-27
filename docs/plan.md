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
| status | Phases 0, 2, 3, 4 and 5 merged (Phase 5 as PR #6, 0.5.15). **Phase 6 (commissioning) planned** (0.6.0, branch `phase-6-commissioning`, 2026-10-27): the photodiode has arrived, not yet mounted. |
| next | Phase 6 step 2: step-and-measure and per-row edge fits, in simulation; then step 3 on the bench, no photodiode needed. Open: the alignment's shift on sharp-spot maps ([hardware](hardware.md#a-map-from-the-window-2026-10-26-and-27)), settled in step 3. |

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

### Phase 6: commissioning

- Install the channel-2 photodiode on an AB corner. Use it to find
  every laser's centre (6 included) and to knife-edge each spot size.
- Repeat the A/B speed test.
- Validate continuous scanning against step-and-measure on a patch.
- Decide whether option C (hardware marker) is needed.
- Ground the flat on the A/B shafts.

**Done when** maps from all six lasers line up, and the sync error is
measured and recorded.

Agreed 2026-10-27 (D22–D24 below). The photodiode (Hamamatsu S1223-01)
has arrived and is not yet mounted, so the bench work that doesn't need
it comes first. Finding lasers, measuring spots and focusing are a
command, `multilbic commission`, and a Lasers tab in the window, both on
the same Tk-free code, as `run` and the run column share theirs.

Steps, each push a 0.6.x:

1. Branch and this plan.
2. **Step-and-measure and edge fits** (simulation): a step-and-measure
   mode on a small patch, which stops at each pixel, waits, and
   averages the SMU there, so its positions involve no timing. Per-row
   edge fits (an error-function edge, giving its position and 10–90 %
   width) as code, not a one-off script: they compare the two modes,
   and the knife-edge scans of step 6 use the same fit. The sync error
   is the shift between continuous rows and step-and-measure, per
   direction and speed.
3. **Bench, no photodiode:** on the test cell's straight right edge
   (`~/cal/stdtest-redge.json`), step-and-measure, then continuous rows
   at 1, 4 and 5 mm/s. That records the sync error (the stamp lag and the
   bunching seen on the stream), checks that 5 mm/s maps hold up (the
   stream at 1000 Hz, the larger shift) so the default speed can move
   from 4 to 5 mm/s (it is 4 since 0.5.16), settles the open alignment finding
   (+9.4 µm from `alignment.py` against +23 µm from edge fits, on the
   sharp-spot map), and gives a first answer on option C. The A/B speed
   test is repeated after the flat is ground, over the full range if the
   grind frees the back edge; if the shafts are not ground by then, the
   repeat moves to step 9.
4. **The photodiode in the simulator:** a `[photodiode]` table in
   `machine.toml` (where it sits on the AB plate, its size, its
   channel; `measured = false` until step 9) and a simulated 3.6 mm
   square chip read on channel 2, its current computed exactly from the
   Gaussian spot as `sim/sample.py` does.
5. **`multilbic commission`** (simulation): for each laser, XY and AB
   bring the photodiode to where the beam should be; lasers with
   unmeasured positions (4–6) start with a coarse search. Rows across
   the chip find its four edges, whose middle is the beam's position.
   Then a reading on the chip's flat top gives the laser's power and
   picks its current range (once on autorange, then the lowest range
   that holds it), and slow rows across one edge along A and one along
   B give the spot size. It ends with the changes it proposes to
   `machine.toml` (`xy_centre_mm`, `spot_um`, `measured = true`) and
   writes them only when the operator says yes (D23). Faults injected
   as in Phase 4.
6. **Focus assist** (simulation, D24): the focus is turned by hand at
   the laser, and by eye a spot can only be judged down to a few tenths
   of a millimetre. With the photodiode parked at one chip edge under
   the chosen laser, the stage passes back and forth across the edge
   (about ±0.5 mm, a pass every second or two) and fits each pass's
   10–90 % width, so the operator turns the focus and sees at once
   whether the spot got sharper or blurrier. It shows the latest width,
   the best so far, a trace of width against time, and the scatter of
   repeated passes, so a real change can be told from noise. Each pass
   re-centres on the edge it last found, since refocusing can move the
   beam; A and B edges can alternate, to show astigmatism. Stopping
   ends with the laser found again and its spot measured, as step 5
   does, since a refocused laser has a new position. The simulator gets
   a focus that can be changed while the loop runs, to test it. The
   command prints one line per pass.
7. **The Lasers tab** in the window: find, measure and focus through
   the worker, a table of the lasers with what was found, the focus
   assist's live readout, and the same save-on-confirm.
8. **Mounting** (the user's job): the can on an AB corner, recessed so
   the chip sits at the sample surface's height, with a shielded twisted
   pair to channel 2 and slack to follow the stage. Then, with no
   motion, a dark reading on channel 2.
9. **Bench, with the photodiode:** read each laser on the chip, focus
   lasers 1–3 with the focus assist (the box is open for this, and the
   stage moves only around the edge, away from the operator's hands at
   the laser), find all six (5 and 6 are near-infrared and invisible: the photodiode is
   the only way to see them, so the box stays closed), knife-edge the
   spots, save. Then a map of the test cell with all six lasers, to see
   that they line up. Docs, changelog, then the PR.

Steps 2 and 4–7 need no machine. Grounding the flat on the A/B shafts is
a mechanical job for the user, at any time before the speed test repeat.

Reachability of the photodiode, worked from `machine.toml` (XY travel
100 × 120 mm, AB ±17.5 mm around its centre, the lasers' XY centres
today): any spot within about 35 mm of the AB centre along A and 60 mm
along B can be brought under every laser, so any corner of the plate
works on paper. Laser 1, near the end of X travel, sets the tightest limit along A. Lasers
4–6 are placeholders, so the margin there is unknown until step 9.

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
| D15 | SMU range during scans | Fixed, `--current-range`, default 25 uA: autoranging drops 10-15 ms of samples at every switch. A run stops if the range clips. One range per run; lasers 1 and 3 need 650 uA on the test cell. |
| D16 | Laser warm-up | Each laser stays on with the stage still for `--warmup` (default 60 s) before its first row, recorded in the file: laser 2 drifted 2x after switch-on. |
| D17 | Where a GUI run lives | In the window's process, on the worker thread (2026-10-26). A crash of the window stops the run as Stop does and keeps the file; a run that must outlive the window is `multilbic run` under `nohup`. The single-instance guard keeps a GUI and a command-line run from opening the same ports. |
| D18 | The live map | Binned row by row as rows finish, **without** the forward/reverse correction; the corrected map, built from the file as the PNG is, replaces it when each laser ends. To be looked at again after the first real runs (2026-10-26). |
| D19 | Jog keys | Arrows, plus the command line's `w a s d q e`, and only while the jog panel has focus, so a stray key can't move the stage (2026-10-26). |
| D20 | Start | A confirm dialog with the lasers, the plan and the estimate, as `run` asks on the command line (2026-10-26). |
| D21 | Python on the Pi | **Deadsnakes' `python3.14` + `python3.14-tk`** (2026-10-26), with Ubuntu's Tk 8.6. uv's own 3.14 has Tk 9.0 built without Xft, so the window's text was jagged (step 7 of Phase 5); Ubuntu's Tk is built with Xft. `deploy/pi/setup.sh` prefers it and falls back to uv's with a warning. CI keeps a uv-managed aarch64 job: the code is the same. |
| D22 | Where commissioning lives | A command, `multilbic commission`, and a Commission tab in the window, on the same Tk-free code (2026-10-27). The command runs under `nohup` like `run`. |
| D23 | Where commissioning results go | Into `machine.toml`, as the proposed changes shown first and written only on the operator's yes; each session's readings also go to a file in `runs/` (2026-10-27). |
| D24 | Focus assist | Focus stays a hand adjustment at the laser; the software measures the spot on the photodiode's edge pass after pass and shows whether it is getting sharper (2026-10-27, asked by the user). No motorised focus. |
| D8 | How LBIC signal is separated from slow drift and mains (dark noise is mostly 0.2–0.7 Hz drift, the band map features occupy at 2 mm/s; see [hardware](hardware.md#streaming-measured-2026-10-19)) | Open, **set aside** (2026-10-20): no enclosure for now. (a) A stable dark enclosure, plus laser-off baselines per row. (b) Chop the laser from the Xiao at a few hundred Hz and demodulate in software (lock-in), with the reference from channel 2 or the Xiao's timing. (b) is the more robust; (a) is needed anyway. Note for (b): the miniSMU tops out near 1.4 kHz and the Pi's reader near 1.2 kHz, so chopping is limited to the low end. Phase 3 does the mains removal and a dark baseline per map; drift would be removed in the per-row cleaning in `scan/binning.py`. |
