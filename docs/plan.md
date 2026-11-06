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
| status | Phases 0–5 and current ranges per sample merged. **Phase 6 (commissioning) on the bench**, branch `phase-6-commissioning`: all six lasers commissioned and placed from the photodiode at every run, two line-ups done (lasers within 39 µm along u, 29 µm along v). |
| next | Close Phase 6: its docs, then the PR. |

## Phases

| Phase | Done when | Outcome |
|---|---|---|
| 0: foundations | `uv sync && uv run pytest` passes in CI and a fresh clone installs on the Pi | PR #1, 0.1.0 |
| 1–2: probes, devices and simulators | every device runs in simulation in CI and on the machine from a script | PR #2, 0.1.11; laser firmware 2.0.0; [hardware](hardware.md) from the first bench sessions |
| 3: scan core | a simulated scan recovers the synthetic sample within tolerance despite 5 ms latency, 20 µm backlash and a 100 ppm clock | PR #3, 0.2.1 ([scan](scan.md#the-simulated-scan)) |
| 4: runs from the command line | a real map comes off the machine without the window | PR #5, 0.4.13: `calibrate`, `run` ([run](run.md)) |
| 5: the window | a full run driven from the window, which also works on the simulator on Windows | PR #6, 0.5.15 ([gui](gui.md)) |
| current ranges per sample | a mixed-range run of lasers 1–3 completes, and a clipping laser steps up | PR #7, 0.5.27 (D25–D27) |
| 6: commissioning | maps from all six lasers line up, and the sync error is measured | below |
| 7: later | | below |

## Phase 6: commissioning

What it built, and where it stands:

- **The sync error, measured**: `sync-check` and `edges`, step-and-measure
  against continuous rows. Dated by count, `L` = 15 ms and an A backlash
  of +4 µm; `ab_backlash_mm` stays 0, the default speed 4 mm/s, no
  hardware marker ([timing](hardware/timing.md#the-sync-check)).
- **The photodiode**: mounted on the new stage under two blades,
  simulated on channel 2, read with `read`
  ([photodiode](hardware/photodiode.md)).
- **Commissioning and focus assist**: `commission`, and the Maintenance
  window's Photodiode and Focus tabs ([commissioning](commissioning.md)).
  All six lasers commissioned (2026-11-03).
- **Wider limits**: Marlin's endstops off, a 5 mm home offset, X to 103
  ([motion](hardware/motion.md#what-multilbic-changes-at-every-connect)).
- **The A/B speed test repeated** after the shafts' flats: 5 mm/s is
  the ceiling.
- **Every map placed from the photodiode**, the servo released after
  each turn: the servo landed each laser differently every selection
  ([lasers](hardware/lasers.md#the-servo)).
- **Timing fixes from six-laser maps**: samples dated by count, late row
  replies and late-starting rows placed right, mains fitted where rows
  are flat ([timing](hardware/timing.md)).
- **The line-up**: each laser's offset on the cell against laser 3, the
  reference since 2026-11-05 (D28). Spread 86/116 µm before the offsets,
  39/29 µm after: about each laser's run-to-run scatter.

Open before the PR:

- Phase 6's docs, and the PR description.

Open, not blocking:

- **Laser 2 is weak and fading** (−47 to −9 µA on the photodiode over a
  week): its supply (lasers 1 and 2 are starved by the 5 V LM317) or its
  cable ([lasers](hardware/lasers.md#the-laser-supply)). A hardware fix.
- **Better offsets**: average several line-ups rather than taking one.
- **Save to Marlin's EEPROM** the 5 mm/s ceiling and A's StallGuard
  threshold of 135, with the home offset put back to 0 first.
- **A plain error when a device's port is missing**, instead of a
  traceback.

## Phase 7: later

- The viewer app: heatmaps, comparing wavelengths, spectral-response
  maps normalised by the photodiode.
- Tiling samples larger than AB's range with XY.
- The TFT35 as a jog pendant, dark during scans.
- Option C (a hardware row marker), only if timing falls short.
- A proper dark enclosure, and with it D8 (slow drift).
- Pi polish: udev rules in the repository, a desktop launcher; the
  Zensical docs site.
