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
| status | Phase 0 landed (0.1.0). Phase 2 in review (0.1.1): drivers and simulators done; flashing the laser firmware and the hardware runs are owed |
| next | first bench session ([bench](bench.md)): firmware updates, then Phase 1 probes and Phase 2's hardware runs over SSH. No PR until those pass. |

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
  - noise floor and offset at 0 V, open circuit and on a dark cell;
  - range switching while streaming.

**Done when** the sync error budget can be checked against measured
numbers, and the stream rate and A/B speed are chosen.

**State (0.1.3):** the probes are written and tested against the
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

### Phase 4: run orchestration and command line

- Home → corner calibration → per-laser loop → rows.
- Stop and fault handling, incremental writing, event log.
- A command-line run of the real machine on a test target.

**Done when** a real map comes off the machine without the GUI.

### Phase 5: GUI

- A Tk window replacing the old one: connection, jog (XY/AB, step size,
  motors on/off), sample setup, calibration steps with a perimeter
  preview, laser select, live heatmap, console, progress and time
  estimate.
- End-of-run plot.

**Done when** a full run is driven from the window, and the window
works against the simulator on Windows.

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
| D6 | How the GUI on the Pi is reached during development | Open; decided in Phase 5. |
| D7 | SMUniversal dependency | Pinned git dependency, installing only what the miniSMU needs. |
