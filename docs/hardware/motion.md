---
type: reference
title: "Motion"
---

# Motion (Marlin)

Upstream **Marlin 2.1.2.4**, environment `LPC1769`, on the BTT SKR 1.4
Turbo. Only `Configuration.h` and `Configuration_adv.h` differ from the
upstream tag (checked 2026-10-17); they are kept in
[`firmware/marlin/`](../../firmware/marlin/) with how to rebuild.

## What is compiled in, and what runs

| Setting | X / Y | A / B | Running |
|---|---|---|---|
| steps/mm | 400 | 3200 | as compiled; 16 microsteps, TMC2209, stealthChop on every axis |
| max feedrate | 20 mm/s | 2 mm/s | A/B **5 mm/s**, sent as `M203` at every connect (the EEPROM holds 6) |
| max acceleration | 100 mm/s² | 50 mm/s² | as compiled |
| motor current | | 800 mA | A/B **600 mA** (EEPROM) |
| StallGuard threshold, `M914` | 96 | 8 | A **135**, sent at every connect; B **130** (EEPROM) |
| homing | sensorless | sensorless | into the hard stop |
| backlash, `M425` | 0.2 mm, correction 0 | | compensation effectively off |

**`EEPROM_SETTINGS` is on, so the board runs what was saved with
`M500`, not the compiled values** (`M503`, 2026-10-19). `machine.toml`
is what MultiLBIC holds to, and `tests/test_hardware.py` reads the live
values. *Later*: save the 5 mm/s ceiling and A's threshold to the
EEPROM with `M500`, in a session with the home offset put back to 0
first, since `M500` saves every setting as it stands.

Other options that matter: `EMERGENCY_PARSER` (`M410` and `M112` act
mid-move: Stop uses `M410`), `ADVANCED_OK` (each `ok` reports planner and
buffer space), `AUTO_REPORT_POSITION`, `M114_DETAIL`.

## What MultiLBIC changes at every connect

Since 0.6.17, so that the photodiode, at the very end of X and A, can be
reached ([photodiode](photodiode.md#reaching-it)):

- **`M211 S0`**: Marlin's software endstops off. Its compiled limits are
  narrower than the machine and would clamp a move silently.
  `machine.toml`'s limits are the only ones, and the client checks every
  move against them before sending it. Marlin turns them on again at
  power-up, so the TFT35 keeps its own.
- **`M206 A5 B5`** (`[ab] home_offset_mm`, not saved): Marlin homes,
  backs off 5 mm (`HOMING_BUMP_MM`), approaches again slowly and sets 0
  there, 5 mm off the stop. With the offset, a homed A and B read 5 and
  0 is the hard stop. After every home the driver checks they read the
  offset and refuses to move if not.
- **Limits**, 0.5 mm clear of each stop: A/B 0.5–39.5 (centre 20),
  X 0–103 (a cable touches the carriage at 104), Y 0–120. Checked at the
  machine 2026-10-30: homed reads A 5, B 5, and about 1 mm is left at
  A and B 1.0 and 39.0.
- Calibrations record the offset; one made before 0.6.17, 5 mm off, is
  refused.

## Speeds

**A/B ceiling 5 mm/s, scans 4 mm/s by default** (D27). Speed trials over
the whole travel after the shafts' flats and grease (2026-11-04, 38 mm
moves, three times there and back, reports `20261104T161837Z` A and
`20261104T162549Z` B):

| Speed | Per 38 mm move (A / B) | Model | Seen and heard |
|---|---|---|---|
| 3 mm/s | 12.84 / 12.83 s | 12.73 s | fine |
| 4 mm/s | 9.68 / 9.68 s | 9.58 s | fine |
| 5 mm/s | 7.80 / 7.80 s | 7.70 s | fine, twice |
| 6 mm/s | 6.55 / 6.55 s | 6.45 s | A vibrated moving back (a resonance); B struggled both ways |

Every speed is reached; each move is the trapezoid model plus Marlin's
0.1 s first-move delay. The first trials, 20 mm moves on A
(2026-10-20, report `20261020T123740Z`), are what
`tests/test_scan_timing.py` checks the model against:

| Speed | Per 20 mm move | Model, without the 0.1 s delay |
|---|---|---|
| 3 mm/s | 6.83 s | 6.73 s |
| 4 mm/s | 5.17 s | 5.08 s |
| 5 mm/s | 4.20 s | 4.10 s |
| 6 mm/s | 3.55 s | 3.45 s |

There is no encoder: lost steps would not show in the timings.

## Behaviour worth knowing

- **The first move after an empty queue waits 100 ms**
  (`BLOCK_DELAY_FOR_1ST_MOVE`): 95–99 ms on the bench beyond the model.
- **A row's `M400` answers a steady 93–96 ms after its `G1` was sent**,
  beyond the move, except for stretches where it comes 20–40 ms late
  ([timing](timing.md#row-replies)).
- **Stop acts at once**: a 2 mm/s move stopped with `M410` after 2.00 s
  had travelled exactly what the first-move delay and acceleration
  predict.
- **For 1 s after a stop Marlin drops moves**, still answering `ok` and
  reporting the dropped move's target as its position
  (`Planner::quick_stop()`). The client sends `M400` before the next
  move.
- **`M114` reports the last commanded position**, not a live one.
- **Releasing the motors loses the position**: Marlin can't see a stage
  pushed by hand. Home again after Motors off.
- `busy:` keepalives arrive every 2 s during long waits; an `M114` round
  trip takes 1.7 ms.

## Homing

- **25–40 s** for all axes, sensorless. Homing first moves every axis
  about 5 mm away, then comes back to find the stop.
- **Repeats to about 0.1 mm over days** (the test cell's corner,
  2026-10-21 against 10-26).
- **A ground against the stop before stopping** at the board's 130: on
  the TMC2209 a *higher* threshold notices the stall sooner. At 135 A
  homes cleanly (2026-11-04); 150 on both axes "found" the stop at once
  wherever they were. B stays at 130.
