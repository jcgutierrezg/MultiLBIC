---
type: reference
title: "Hardware"
---

# Hardware

What the machine is, as far as the code, the firmware and the builder's
memory agree. **Nothing here has been measured with this software yet.**
The machine has never run a complete scan. Everything marked *unverified*
is a claim waiting for its Phase 1 bench probe (see [plan](plan.md)).

## Topology

```
Raspberry Pi 4, Ubuntu 24.04 (monitor attached, runs the GUI)
 ├── USB  BTT SKR 1.4 Turbo, Marlin 2.1.2.4    /dev/SKR       motion: X Y (Z) A B
 ├── USB  Seeeduino Xiao "laser board"          /dev/S_LASER   servo revolver + 6 laser enables
 ├── USB  Undalogic miniSMU MS01                (by serial)    photocurrent, ch1 (ch2 free)
 └── USB-TTL  BTT TFT35 touchscreen             /dev/TFT35     wired, currently unused
```

The `/dev/...` names came from udev rules on an earlier install. The
current Ubuntu install (checked over SSH on 2026-10-19) has **no such
rules**, so the boards appear as plain `/dev/ttyACM*` and `/dev/ttyUSB*`.
All four identified over SSH on 2026-10-19. Port numbers depend on
plug-in order, so the serial number is what identifies a board.
`machine.toml` uses the names Linux builds from it under
`/dev/serial/by-id/`, which need no udev rules:

| Board | Port then | USB id | Serial number |
|---|---|---|---|
| SKR 1.4 Turbo (Marlin) | `/dev/ttyACM0` | `1d50:6029` "Marlin_USB_Device" | `1602400395D510E961DB1B78F50020C1` (line 2 of `Serials.txt`) |
| Laser Xiao | `/dev/ttyACM1` | `2886:802f` "Seeed_XIAO_M0" | `AC5401405154315432202020FF102436` (line 3 of `Serials.txt`) |
| miniSMU | `/dev/ttyACM2` | `303a:82a6` "miniSMU_MS01" | `lunar-tuvok-7966` (lower case over USB) |
| TFT35 adapter | `/dev/ttyUSB0` | `0403:6001` FTDI TTL232R-3V3 | `FTDKEIR6` (not in `Serials.txt`) |

The laser Xiao answered `ID?` with `MultiLBIC-Laser,2.0.0`. That proves
the firmware, not the wiring: that this is the board driving the lasers
and servo is confirmed only when the laser probe's `--lasers` stage
lights them.

Line 1 of [`deploy/pi/Serials.txt`](../deploy/pi/Serials.txt)
(`C17AF51C5154315432202020FF110F18`) is the other SAMD21. By
elimination it is the retired instrumentation Xiao. It was not connected.

The second Xiao, the "instrumentation" board, is gone. The miniSMU
replaced it, and nothing should still refer to it.

## Mechanics

- **The XY stage carries the whole AB gantry.** Both stages move the
  sample, so their degrees of freedom overlap. Their jobs differ:
  - **AB** does the raster. 1 mm lead screws, 3200 steps/mm, so 0.3125 µm
    per microstep. 40 mm of travel; centre 17.5 mm.
  - **XY** puts the AB centre under the chosen laser and moves samples
    larger than the AB range. 2 mm lead screws, 400 steps/mm (2.5 µm).
- **The AB back edge is not usable.** Close to it the motor struggles or
  the grub screw slips. The safe range is about 0–35 mm. The grub screw
  sits on the shaft's thread. A flat ground into the shaft is the
  planned fix (small hardware change, owed). **Done** (the builder,
  2026-11-04): the thread where the motor coupling sits is flat and
  tight, and the A/B rods have lithium grease since the speed trials of
  2026-10-20. The "back edge" itself was the far stop (below).
- **XY and AB move the sample the same ways** (bench, 2026-10-21,
  laser 2 on a mark): +X moves it the same way as +A, +Y the same way as
  +B, and both stages home to the same corner. So `x_along = "+A"`,
  `y_along = "+B"` in `machine.toml`. (The note at the time said "+X and
  +A move it up, +Y and +B right"; that was from a different viewpoint
  than the one below, and only the pairing matters.)
- **What a scan looks like at the machine** (bench, 2026-10-23, watched
  with the box off, seen as in the reference photo of the test cell):
  the spot starts at the sample's **top-right corner**, each row runs
  **leftwards** (+A), and the rows step **downwards** (+B). So the
  calibration corner is the top-right one (the old script asked for the
  top-right corner too), and on the test cell the rows run along the
  fingers. `[display]` in `machine.toml` (`u_points = "left"`,
  `v_points = "down"`) draws map PNGs the same way round.
- **The stage moves the other way from the spot** (the builder,
  2026-10-28): **+A and +X move the stage to the right**, as the
  operator stands, and so the spot left over the sample; +B and +Y move
  the stage up in that view, the spot down. Notes that say how "the
  sample" or "the mark" moved meant the spot. Since 0.6.6 the window's
  jog arrows move the stage the way they point.
- **Z has a driver and no motor.** Marlin would not build XYAB without
  Z. The software never moves Z.
- **Samples** are solar cells, 100–300 µm thick, typically 10, 20 or
  30 mm square. There is no focus axis, so spot size relies on sample
  height being roughly constant.

## Lasers

Six lasers sit fixed on a servo-driven revolver. The servo turns only
180°, so they are mounted as **two groups of three**. Lasers 1/4, 2/5 and
3/6 share a servo angle. XY selects the group by moving the AB centre
under it.

| Laser | Wavelength | Servo angle | XY centre (mm) | Status |
|---|---|---|---|---|
| 1 | 444 nm | 150° | 79.6, 71.3 | measured once |
| 2 | 519 nm | 90° | 75.6, 71.7 | measured once (used for alignment) |
| 3 | 652 nm | 30° | 75.0, 70.0 | measured once |
| 4 | 676 nm | 150° | 49.4, 43.0 | probably placeholder |
| 5 | 785 nm | 90° | 49.4, 43.0 | probably placeholder |
| 6 | 848 nm | 30° | 50.0, 50.0 | placeholder (IR, needs a detector card) |

Lasers 4 and 5 have identical coordinates, which is what gives them away
as placeholders. Spot sizes have not been measured. Lasers are below
class 2 (*unverified*). The planned dark enclosure must not interrupt a
run.

### Laser board firmware

[`firmware/laser/MultiLBIC_Laser/MultiLBIC_Laser.ino`](../firmware/laser/MultiLBIC_Laser/MultiLBIC_Laser.ino)
is now **version 2.1.0** (2026-11-05; 2.0.0 in Phase 2). Its
protocol is in [devices](devices.md#laser-board-protocol-21). Pins and angles are
unchanged: laser enables on pins 1, 2, 3, 4, 5, 8, servo on pin 9, and
pins 0, 6, 7 and 10 free.

What changed from the 1.x sketch:

- 1.x replied in free text (`Servo moved to: 90`), with no ack/error
  convention, no identify and no state query. 2.0 sends one reply line
  per command.
- 1.x always busy-waited 2 s. In 2.0 the settle time can be set, and is
  skipped when the servo is already at the angle.
- 1.x parked the servo at 90° on `LASER 0`. 2.0 leaves it where it is.
- 2.1 releases the servo once it has turned and settled (`RELEASE`),
  because held powered it kept moving the beam (below, 2026-11-05).

**2.0.0 is on the board** (flashed 2026-10-19; `ID?` answers
`MultiLBIC-Laser,2.0.0`, `STATE?` answers `STATE 0 90`). The driver
refuses 1.x firmware at `open()`. A laser gate input driven by Marlin comes
later, and only if software sync is not good enough (see
[architecture](architecture.md#position-sync)).

### Lasers, checked on the bench 2026-10-20

Reports `bench-results/20261020T130654Z_laser_real.json` and
`20261020T140042Z_laser_real.json`, plus a one-at-a-time check with the
builder watching.

- **Timing is exact.** A switch that moves the servo takes the settle
  time to within 1 ms. A same-angle switch (1↔4, 2↔5, 3↔6) takes 1 ms.
  `STATE?` round trip: 0.42 ms.
- **Each laser lights alone, at the right angle.** One at a time, held:

  | Laser | Seen | Servo |
  |---|---|---|
  | 1 | one blue-violet beam | 150° |
  | 2 | one green beam | 90° |
  | 3 | one red beam | 30° |
  | 4 | one deep red beam | 150° |
  | 5 | dim deep red by eye, clear on a phone camera | 90° |
  | 6 | nothing by eye, clear on a phone camera | 30° |

  So this Xiao drives the lasers and servo, and every enable line is its
  own. During the fast probe the builder saw two lasers lit at once.
  Held one at a time, none ever was. The likely cause is the same-angle
  swaps, where one laser goes off and the next comes on within 1 ms.
- **Servo settle, worst case** (120° swing, 30° → 150°, onto laser 1):
  **1000 ms: the spot appeared and stayed put**, twice. **500 ms: the
  spot slid a little after appearing**, so too short. Decision D10
  keeps **2000 ms**, set from `machine.toml` (`[laser_board] settle_ms`)
  at every `open()`, since the firmware forgets a runtime value on
  power-up.

## Motion controller (Marlin)

Upstream **Marlin 2.1.2.4**, environment `LPC1769`. Only
`Configuration.h` and `Configuration_adv.h` were changed: checked by
diffing the original folder against the upstream tag on 2026-10-17, with
no other file different. Those two files are kept in
[`firmware/marlin/`](../firmware/marlin/); how to rebuild is in its
README.

Compiled-in values that matter to the software:

| Setting | X / Y | A / B | Note |
|---|---|---|---|
| steps/mm | 400 | 3200 | 16 microsteps, TMC2209 |
| max feedrate | 20 mm/s | **2 mm/s** | the board runs **6 mm/s** from EEPROM, and `machine.toml` now uses 6 too (D9) |
| max acceleration | 100 mm/s² | 50 mm/s² | reaching 2 mm/s takes 0.04 s over 0.04 mm |
| travel | 0–100 / 0–120 | 0–40 | software endstops on as compiled; MultiLBIC turns them off (`M211 S0`) and keeps to `machine.toml`'s limits (since 0.6.17) |
| homing | sensorless | sensorless, stall sensitivity 8 | drives into the hard stop |

Other relevant options:

- **Zero is about 5 mm off the hard stop, on A and B at least** (the
  builder, 2026-10-29: homing crashes into the stop, yet `A0 B0` leaves
  a 5 mm gap). `HOMING_BUMP_MM` is `{ 5, 5, 5, 5, 5 }` with
  `SENSORLESS_HOMING`: after the first stall Marlin backs off 5 mm and
  approaches again at a quarter of the homing speed on A/B (1 mm/s),
  half on X/Y. StallGuard is unreliable that slowly, and A/B run a
  sensitive threshold from EEPROM (130, against 8 compiled), so the
  second approach most likely "stalls" at once and 0 is set where the
  back-off left the carriage. Marlin's own comment in
  `Configuration_adv.h` recommends a bump of 0 with sensorless homing.
  Home offsets (`M206`) are all 0, so nothing else moves the zero.
  - *Unverified*: whether X/Y stop short the same way.
  - **A/B have 40 mm between their hard stops, X goes to 105** (the
    builder, 2026-10-29). So a zero 5 mm in left only up to 35 before
    the far stop: the "back edge" (the motor struggling past 35) was the
    far stop, not the grub screw.
- **Changed without recompiling (0.6.17, 2026-10-29)**, because the
  photodiode is reached at the very end of X and A (laser 1 had 0.7 mm
  past the corner), and the builder prefers wider limits to a rebuilt
  stage or a special case:
  - **`M211 S0` at every connect**: Marlin's software endstops off.
    Its compiled limits (X 100, A/B 0-40 from its own zero) are
    narrower than the machine, and a move past them would be clamped
    silently. `machine.toml`'s limits are the only ones, and every move
    is checked against them before it is sent. Marlin turns them on
    again at power-up, so the TFT35 keeps its own.
  - **`M206 A5 B5` at every connect** (`[ab] home_offset_mm`, not saved
    to EEPROM): once homed, A and B read 5, so 0 is the hard stop and
    the full 40 mm is usable. After every home the driver checks that A
    and B read the offset, and refuses to move if not: an offset taken
    the other way round would put 39.5 past the far stop.
  - **Limits** with 0.5 mm kept clear of each stop: A/B 0.5-39.5
    (centre 20), X 0-104.5. **X lowered to 103 (0.6.18, 2026-10-30)**:
    at 104 the carriage just touches a cable (the limit check).
  - **Every A/B coordinate moved by +5 mm**: positions noted before
    0.6.17 read 5 less than today's for the same place. The
    photodiode's corner moved with them (59.7, 23.6), `xy_centre_mm`
    did not (XY is unchanged). Calibrations record the offset; one
    made before is refused (`CalibrationMismatch`): calibrate again.
  - Laser 1 now reaches 3.2 mm past the corner (4.7 with X to 104.5),
    lasers 2 and 3 7.2 and 7.8 mm.
  - *Checked at the machine* (2026-10-30): home reads A 5, B 5; about
    1 mm left at A and B 1.0 and 39.0; X at 104 touches a cable, hence
    103.
- `EMERGENCY_PARSER`: `M410` (quickstop) and `M112` act mid-move. This is
  what Stop uses.
- `ADVANCED_OK`: each `ok` reports free planner and serial buffer space.
- `BACKLASH_COMPENSATION` + `BACKLASH_GCODE` are on, with distance
  0.2/0.2 mm on X/Y and correction 0.0 compiled in.
- `AUTO_REPORT_POSITION`, `M114_DETAIL`, `M115_GEOMETRY_REPORT`,
  `HOST_ACTION_COMMANDS`, `HOST_PROMPT_SUPPORT`.
- `SERIAL_PORT_2 -1`: a second serial console on USB, unused.
- **`EEPROM_SETTINGS` is on, and the board does not run the compiled
  values.** `M503`, read on the bench 2026-10-19 (firmware built
  20 May 2025):

  | Setting | Compiled | Running (EEPROM) |
  |---|---|---|
  | A/B max feedrate, `M203` | 2 mm/s | **6 mm/s** |
  | A/B motor current, `M906` | 800 mA | **600 mA** |
  | A/B StallGuard threshold, `M914` | 8 | **130** |
  | X/Y StallGuard threshold | 96 | 96 |
  | backlash, `M425` | X/Y 0.2 mm, correction 0 | the same, so compensation is effectively off |
  | stepping mode, `M569` | | stealthChop (S1) on every axis |

  So the old script's `F360` really did run A/B at 6 mm/s. After the
  speed trials, `machine.toml` was raised to 6 mm/s to match (decision
  D9). `tests/test_hardware.py` checks that the two agree.
- Plain `M114` reports the last **commanded** position, not a live
  one (see [devices](devices.md#marlin)).
- **Releasing the motors loses the position.** Marlin cannot see a
  stage pushed by hand, so after `M18` its coordinates mean nothing
  until the next home. The old workflow (torque off, push the stage to
  the corner, read `M114`) would have recorded the position from
  before the push. Corner calibration has to jog with the motors on.
- Marlin waits **100 ms** before starting the first move after its queue
  was empty (`BLOCK_DELAY_FOR_1ST_MOVE` in `planner.cpp`). This is one of
  the timing offsets the old script ignored.

The builder remembers choosing 2 mm/s as the smoothest and fastest
speed in an earlier test, yet the EEPROM holds 6 mm/s. The speed trials
(below) ran A smoothly up to 6 mm/s. A/B speed is what sets the run time
(see [architecture](architecture.md#run-time)).

Measured 2026-10-19: an `M114` round trip takes **1.7 ms** median
(2.1 ms max). The board was unhomed at power-up, all axes at 0.

### Motion, measured 2026-10-20

Report `bench-results/20261020T123740Z_marlin_real.json` (commit
`14db999`). Probe lifted, stage clear, `--home --motion`:

- **Homing all axes takes 33.5 s**, sensorless, without incident.
- **Speeds are exact**: fitting time against distance for 1–10 mm moves
  gives 0.999–1.000 mm/s at 1 mm/s and 2.000 mm/s at 2 mm/s, on A and
  on B. Nothing is clamped below 2 mm/s, as expected with 6 mm/s in
  EEPROM.
- **Each move carries a fixed 113–135 ms**, 95–99 ms more than the
  trapezoid model alone. That is Marlin's 100 ms first-move delay, seen
  on the hardware. Model plus delay predicts a move's duration to within
  about 5 ms.
- **Stop acts at once**: a 2 mm/s move stopped with `M410` after 2.00 s
  had travelled 3.763 mm. The 120 ms shortfall is exactly first-move
  delay plus acceleration, so no lag is left for the stop itself.
- **For 1 s after a stop Marlin ignores moves.** The `M400` after `M410`
  took 1.0 s. Marlin's `Planner::quick_stop()` drops every new move for
  one second while still answering `ok`, and `prepare_line_to_destination()`
  still sets the reported position to the dropped move's target. A move
  sent right after Stop would be lost silently, with `M114` claiming it
  happened. The client now waits that second out with `M400` before the
  next move (0.1.6).
- `busy:` keepalives arrive every 2.000 s during long waits.
- **Repeatable**: a second run 10 minutes later (report
  `20261020T124649Z`, commit `503f2a1`) gave the same per-move overheads
  (115–135 ms), the same stop at 3.763 mm, and homing in 25.5 s.

**A speed trials** (same report): A only, three 20 mm round trips per
speed, with `M203` raised for the run and restored to 6 mm/s afterwards.
X, Y and B did not move.

| Speed | Per 20 mm move | Model, without the 0.1 s first-move delay |
|---|---|---|
| 3 mm/s | 6.83 s | 6.73 s |
| 4 mm/s | 5.17 s | 5.08 s |
| 5 mm/s | 4.20 s | 4.10 s |
| 6 mm/s | 3.55 s | 3.45 s |

Every speed was reached: each move is the model plus Marlin's 0.1 s
delay. **By eye and ear, all four were smooth, with no clicking,
grinding or overshoot** (the builder, watching). Lost steps would not
show in the timings; there is no encoder.

**B speed trials** (report `20261020T141756Z`, commit `339c84c`, B only):
6.82, 5.18, 4.20 and 3.55 s per 20 mm move at 3, 4, 5 and 6 mm/s, which
matches A to within 10 ms. By eye and ear: **no missed steps, but 6 mm/s
was noticeably noisier and vibrated more than 3–5 mm/s.** Vibration
moves the beam spot relative to the sample, so scans should stay at
**5 mm/s or below** unless a map shows otherwise (D9).

**Speed trials again, across the whole travel (2026-11-04)**, after
the coupling's flat and the rods' grease: 38 mm moves (1 to 39 mm),
three times there and back at each speed (`bench.marlin --speeds
3,4,5,6 --speed-span 1,39`, reports `20261104T161837Z` A and
`20261104T162549Z` B):

| Speed | Per 38 mm move (A / B) | Model | Seen and heard (the builder) |
|---|---|---|---|
| 3 mm/s | 12.84 / 12.83 s | 12.73 s | fine |
| 4 mm/s | 9.68 / 9.68 s | 9.58 s | fine |
| 5 mm/s | 7.80 / 7.80 s | 7.70 s | fine, again on a second run of both |
| 6 mm/s | 6.55 / 6.55 s | 6.45 s | A vibrated moving back (a hand on the motor stopped it: a resonance); B struggled both ways, even pressed |

- **The A/B ceiling is 5 mm/s** (`max_feed_mm_s`), sent to Marlin as
  `M203` at every connect; the EEPROM still has 6. Scans default to
  4 mm/s (D27).
- **A's homing grinds against the stop before stopping** (the builder):
  StallGuard is slow to see the stall. On the TMC2209 a *higher* `M914`
  notices sooner (0-255); the EEPROM has 130. 0.6.39 sent 150 to both
  axes at every connect, and both then "found" a stop at once (homing in
  15.5 s, from wherever they were: positions meaningless until homed
  again). Since 0.6.41 each axis has its own key: `stall_threshold_a =
  135`, and B is left at the board's 130 (no `stall_threshold_b`):
  A homed cleanly at 135 (24.5 s, the builder listening). Homing first moves every axis about 5 mm
  away, then comes back to find the stop (the builder). *Later*: once settled, save it (and the 5 mm/s ceiling) to
  the board's EEPROM with `M500`, in a session with the home offset put
  back to 0 first, since `M500` saves every setting as it stands.
- Homing took 40.6 s once and about 20 s the other three times.

## First maps, 2026-10-21 to 2026-10-23

Phase 4's bench session ([bench](bench.md#phase-4-first-maps)), on the
18 x 18 mm test cell ("stdtest"), laser 2 unless stated, in a cardboard
box with the room lights on. Run folders are named by their UTC stamp.

- **The box works.** Laser-off baseline −0.4 to −20 nA with 0.7-1.5 nA
  RMS, mostly drift below 0.5 Hz. With the room lights on, the bench had
  measured 1.7 uA RMS: about a thousand times quieter.
- **The lead to the backplate matters.** It is a crocodile clip biting
  the copper backplate. Homing A drives the stage to the end away from
  where the lead came in and tugs it. A loose clip gave a flat map
  (`20261021T174652Z`, lead off) and, partly loose, row-to-row jumps of
  2-3x in the photocurrent (`20261023T151932Z`). With the leads coming
  in from the top and strain-relieved, the level is steady
  (`20261023T153728Z`) and about twice what it was before. A soldered or
  screwed connection to the backplate would be better than a clip.
- **Signal**, laser 2 on the cell: −0.3 to −1.0 uA, rising towards the
  wire contact. Laser 1 (444 nm) gave more than 25 uA, clipping the
  25 uA range (`20261023T163133Z`, stopped by the saturation check).
- **Spot**, laser 2, focused by eye: the cell's straight right edge goes
  from 10 % to 90 % in 123-132 um at both 1 and 4 mm/s, so sigma is
  about 50 um and the 1/e^2 diameter about 0.2 mm. Resolution is set by
  the spot, not the pixels. Lasers 1 and 3 were focused by eye too;
  their spots are measured properly with the photodiode (Phase 6).
- **On the cell, with the laser on, the signal has 100-200 Hz noise**
  of about 20 % per 10 um pixel at 1 mm/s, absent with the laser off or
  off the cell. With a 0.2 mm spot this is not surface texture; most
  likely the laser's own output. Larger pixels average it.
- **The forward/reverse shift** on the straight edge, 40 rows 50 um
  apart (`20261023T155130Z`, `20261023T155424Z`):

  | Speed | Shift | Spread between row pairs |
  |---|---|---|
  | 1 mm/s | +20.5 um | 7.7 um |
  | 4 mm/s | +131.9 um | 12.5 um |

  It grows by 37 um per mm/s: a timing lag of **18.6 ms with the
  samples stamped after they were measured**, which supports the
  "stamped when sent" suspicion above. The fit's offset at zero speed
  is −17 um, which cannot be backlash; A backlash is too small to see
  this way, so `ab_backlash_mm` stays 0. The serpentine alignment
  removes the shift per map; the residual is the 8-13 um row-to-row
  spread.
- **The alignment needed broader smoothing.** Smoothing rows over 2 um
  (right for the simulator's 5 um spot) only correlated noise with a
  0.2 mm spot. It now tries 2-80 um and keeps the finest that a clear
  majority of row pairs agree on (0.4.10).
- **What the cell looks like** (whole-cell surveys, `20261023T125741Z`,
  `20261023T153728Z`): the rows run along the fingers, so fingers show
  only as faint bands; the copper strip above the cell's top edge; an
  electrically dead region at the bottom-right, next to the pad that
  broke in the first soldering attempt, with a straight slanted
  boundary; small dead patches at the wire and solder blob; current
  rising towards the contact. The calibrated corner sat about 1.3 mm
  inside the cell's right edge and 0.5 mm below its top edge: picking a
  corner by eye with a 0.2 mm spot is good to about a millimetre.
- **Stop** (`20261023T160531Z`): SIGINT after row 10 left a readable
  file with 10 rows and status `stopped`.
- **Three lasers on the straight right edge** (step 7, after refocusing
  all three by eye; `20261023T163531Z` laser 2, `20261023T163839Z`
  laser 1, `20261023T164506Z` laser 3; 2 x 2 mm, 1 mm/s):

  | | Laser 1 (444 nm) | Laser 2 (519 nm) | Laser 3 (652 nm) |
  |---|---|---|---|
  | Current on the cell | −60 uA | −0.71 uA | −77 uA |
  | Range needed | 650 uA | 25 uA | 650 uA |
  | Edge 10-90 % (spot) | 65 um | 41 um (125-130 um before refocusing) | 244 um |
  | Offset along A, from the edge | 0 | −0.14 mm | −0.01 mm |
  | Offset along B, from a finger | 0 | about −0.30 mm | −0.12 mm |
  | Forward/reverse shift | +10.1 um | +11.9 um | +39.4 um |

  - Offsets are relative to laser 1, with XY placed from today's
    `xy_centre_mm`. B comes from where a finger (which runs along the
    rows) appears; fingers repeat every ~1.0 mm, so B is known modulo
    that, and the small values are taken. Refocusing moved laser 2's
    edge by ~0.13 mm, so its beam moves with focus; it is also the
    calibration's reference laser. The lasers register to within about
    0.3 mm; the photodiode measures all six properly (Phase 6).
  - **Laser 2 gives about 1/100 of the current of lasers 1 and 3**,
    which the cell's response at 519 nm does not explain: laser 2 is
    probably weak.
  - **Laser 2's output rose about 2x over its run**, which started right
    after it was switched on; lasers 1 and 3 stayed within 5 %. Hence
    `run --warmup` (default 60 s), which also records the warm-up so
    the settling can be seen (row −2 in the file).
  - The shift differs by laser (10-39 um at 1 mm/s), so it is not
    timing alone: the cell's response to each spot adds to it. The
    alignment measures it per map either way.
  - The finger shows deeper under the sharp spot (14 %, laser 1) than
    under the broad one (4 %, laser 3).

## A map from the window, 2026-10-26 and 27

Phase 5's bench session ([bench](bench.md#phase-5-a-map-from-the-window)):
the patch on the cell's straight right edge (`stdtest-redge`) again,
laser 2 at 1 mm/s, from `multilbic gui`.

- **Homing holds to about 0.1 mm over days.** The cell's top-right
  corner, found by eye with laser 2, was at A 17.6, B 17.4 against
  A 17.5, B 17.5 on 2026-10-21, XY unchanged.
- **The edge moved and sharpened.** Against the command-line map of
  2026-10-23, the edge sits 0.2 mm further into the patch, its 10-90 %
  width is far narrower, and it now shows a bow of about 0.1 mm over the
  2 mm. Laser 2 was refocused by eye in between (about 0.2 mm spot then,
  41 um after), which can move the spot sideways as well as sharpen it.
  The signal on the cell was about 600 nA against 1000 nA.
- **The window adds no timing error.** Row times from sent to finished
  match the command-line run's to 0.2 ms (median 2.3158 s, same 12 ms
  spread, reverse rows 14 ms longer in both: Marlin, not us).
- **The shift, measured from the edge:** +23 um (neighbouring rows),
  against +17 to +20 um on 2026-10-23: the same machine. **The map's
  alignment said +9.4 um.** On the old, blurrier map it agreed with the
  edge (19.6 against 19.8 um); on this sharp one it does not. Worth a
  look at `scan/alignment.py` with sharp-spot maps before relying on its
  number.
- STOP, Esc and closing the window each stopped a row in progress at
  once; the files kept every finished row.

### Edge fits on these maps, 2026-10-28

`multilbic edges` (Phase 6 step 2) on the straight-edge maps above: an
error function fitted to every row, its 50 % point the edge, the
forward/reverse shift from each row against its two neighbours (so the
edge's bow cancels).

| Map | Laser | Speed | 10-90 % width | Shift from edges | Alignment |
|---|---|---|---|---|---|
| `20261023T155130Z` | 2 (before refocus) | 1 mm/s | 149 um | +21.4 um | +19.6 um |
| `20261023T155424Z` | 2 (before refocus) | 4 mm/s | 157 um | +139.1 um | +138.7 um |
| `20261023T163839Z` | 1 | 1 mm/s | 62 um | +17.3 um | +10.1 um |
| `20261023T164506Z` | 3 | 1 mm/s | 145 um | +30.9 um | +39.4 um |
| `20261026T173940Z` | 2 (refocused) | 1 mm/s | 36 um | +19.9 um | +9.4 um |

- **The alignment is right on broad spots and off on sharp ones**:
  within 2 um where the spot was ~150 um, 7-10 um off on lasers 1 and 2
  after refocusing. The edges give +17 to +21 um at 1 mm/s for every
  laser but 3, which fits one timing error for all. So the open finding
  (+9.4 against +23 um) is the alignment, not the machine; the sync
  check measures it properly.
- **Laser 3's width depends on how it is measured**: 145 um from the
  error-function fit, against the 244 um read from the binned map's 10 %
  and 90 % points (`spot_um` in `machine.toml`). A spot with wings, not
  a Gaussian, would do that. The photodiode's knife-edge scans will
  say.

## Current ranges on the test cell, 2026-10-27

Ranges step 6 ([bench](bench.md#current-ranges-the-bench)), the same
patch (`stdtest-redge`), 0 V.

| | Laser 1 (444) | Laser 2 (519) | Laser 3 (652) |
|---|---|---|---|
| Check's brightest (no warm-up) | 24 uA | 2.3 uA | 92.7 uA |
| Range chosen (3x) | 650 uA | 25 uA | 650 uA |
| Map's brightest (after 60 s warm-up) | 96.9 uA | 3.06 uA | 118 uA |
| Map / check | 4.0 | 1.3 | 1.3 |

- **Laser 1 read 4x less in the check than in the run.** Not warm-up:
  the run's warm-up samples show laser 1 only 10 % brighter after its
  minute (-2.04 to -2.26 uA, spot parked off the sample), lasers 2 and
  3 flat. Not autorange either (below). It is laser 1 being relit too
  soon after going off (next point); a check run from a script read
  84.3 uA against 84.5 uA parked.
- **Laser 1 relit too soon comes back at 40 % and stays there.** Parked
  on the bright part, the servo kept on laser 1's angle, only the time
  dark changed (three tries each):

  | Dark before relighting | 0.25 s | 0.5 s | 1 s | 1.5 s | 2 s | 3-5 s |
  |---|---|---|---|---|---|---|
  | Laser 1, uA | 38-41 | 38-39 | 38-39 | 39, 86, 40 | 85-86 | 85-87 |
  | Laser 3, uA | 101.4 | 101.5 | 101.6 | 101.5 | 101.5 | 101.6 |

  Held on after a short break it crept from 38 to 42 uA in 30 s, no
  further. It is the laser (or its driver), not the servo: the firmware
  doesn't move the servo for a laser already at its angle, and from
  laser 2 or 3 (at least 2.5 s dark, servo moving) laser 1 always came
  back at 86 uA. Runs were safe (a 3 s baseline dark before each
  laser); checks and clicks were not. Since 0.5.25 the driver keeps a
  laser dark for `[laser_board] relight_ms` (3000) before relighting
  it, and selecting the laser already on sends nothing (the firmware
  would switch it off and on).
- **Autorange doesn't stick.** Parked on laser 1's bright part (93 uA),
  single readings on autorange read 93.3 uA against 92.7 uA on fixed
  650 uA. After each reset the first reading or two sit at 1.03 uA (the
  1 uA range's end) while it climbs. A range that truly clips reads its
  end exactly: 26.78 uA every time on 25 uA. The check's re-read near a
  range's top (0.5.24) stays as a safety net.
- **Laser 1 drifts**: parked, 93 to 80 uA over half a minute in one
  session, 84-87 uA in the next.
- **The cell's contact changes when the stage moves** (2026-10-28).
  Two checks, each the first after the window homed (2026-10-27 17:31,
  2026-10-28 15:23), read 0.1-12 nA on every laser: no circuit. A
  stress test homed five times, parked laser 1 on the bright part and
  set the SMU up afresh ten times per round. Within a round the reading
  never changed; between rounds it was 0.3 uA, dark then 80 uA, 80 uA,
  dark, 68 uA. Without motion, laser 1 switched on 20 times (3 s dark
  between) read 66-69 uA every time. The lasers are fixed to the
  frame; the cell and its crocodile-clip leads ride on the stage, so
  homing's jolts most likely make or break the contact. **Not only the
  leads** (the builder, 2026-10-28): the cell's back contact presses on
  the copper backplate only through Kapton tape at its edges, nothing
  pushes it down from the top, and it loses pressure as the stage
  moves. Pressing the edges down by finger brought laser 1 back up to
  40 uA. **Not fixed in software**: the new stage solders the contacts
  and should hold the cell down from the top. Until then, a check or
  map reading nA where uA is expected means the contact: press the
  cell's edges down, reseat the clips, and run it again.
- **The current limit at the range's full scale works**: the SMU took
  25 uA and 650 uA limits. A 25 uA range clipped at 26.8 uA, just over
  full scale.
- **Single readings agree with the stream** at the same spot (-37 to
  -47 nA against -46 nA, laser 2), so the check's readings are good.
  The light reaches the cell within 0.25 s of `LASER n`, then laser 2
  brightens about 25 % over 4 s.
- **A session where the SMU read almost nothing**: the first check
  read 1-12 nA where the grid holds uA, and the window's readout 140 pA
  dark. The next window session read normally; the cause (the output
  not on, or the contact) is not known. A check that reads only nA on a cell that
  should give uA is the sign.

## Source-measure unit

The same **Undalogic miniSMU MS01** that SMUniversal uses (serial
`LUNAR-TUVOK-7966`, firmware 1.4.6). SMUniversal's bench record for it
is in `SMUniversal_Lab_Suite/docs/instruments/undalogic-minismu.md`.

- **Channel 1** measures photocurrent at 0 V bias. Expected signal: low
  µA down to nA, *unverified*.
- **Channel 2** is free. Agreed use: a reference photodiode on a corner
  of the AB stage, outside the sample area. The part arrived 2026-10-27
  and is not yet mounted ([below](#channel-2-reference-photodiode-chosen-2026-10-22)).
- **Envelope:** two channels, four-quadrant, ±12 V, ±180 mA, 2.1 W per
  channel. Five current ranges: 1 µA, 25 µA, 650 µA, 15 mA, 180 mA (from
  `minismu_py` and SMUniversal's driver). On USB-C power alone each
  channel is limited to 50 mA, and the instrument can't say which
  supply it is on, so the 12 V adapter stays plugged in.
- **Streaming** (`SOUR<n>:DATA:STREAM`, rate set with
  `SOUR<n>:DATA:SRATE`, packets timestamped by the SMU's own clock) is
  what makes continuous scanning possible. First measured on this
  bench, 2026-10-19; findings below.
- SMUniversal measured **150–180 nA open-circuit current at 0.1 V** on
  this unit.
- Firmware is still **1.4.6**: Undalogic's update server returned HTTP
  500. The library says 1.5.0+ adds the active current range to each
  packet.

### Channel-2 reference photodiode, chosen 2026-10-22

What it is for is in
[architecture](architecture.md#the-channel-2-reference-photodiode):
laser positions, knife-edge spot sizes, and a power reference to
compare wavelengths.

**Chosen: Hamamatsu S1223-01**, RS 415-5722 (about £17–18 ex VAT on RS
UK, October 2026). **Arrived 2026-10-27**, not yet mounted.

| Need | S1223-01 |
|---|---|
| All six lasers, 444–848 nm | Si PIN, 320–1100 nm; 0.52 A/W at 780 nm, peak at 960 nm |
| Active area much larger than any spot | 3.6 × 3.6 mm: a position scan sees a flat plateau with clean edges |
| An edge for knife-edge scans | The square chip edge, in the chip's plane; a razor blade on top if a spot turns out large |
| No lens | Metal TO-5 can with a flat window; a lensed part responds differently depending on where the spot lands |
| A spectral curve to correct by | Hamamatsu publishes the typical curve, which wavelength normalisation needs |

Specifications from Hamamatsu's product page; price and stock from RS's
listing, which change.

- **Fallback:** Vishay BPW34, RS 699-7616 (pack of 5, a few pounds).
  Larger (7.5 mm²) but its range starts at 430 nm, close to laser 1,
  and the clear plastic package is less well defined. Good for trying
  the mount and the cable first.
- **Avoid**, although RS lists them as photodiodes: eye-response (V(λ))
  filtered parts such as BPW21 or Hamamatsu S1087/S7686, which cut off
  near 700 nm and would miss lasers 5 and 6; daylight-filtered infrared
  parts such as BPW34F, SFH 205F or BPW41N, whose black epoxy blocks
  444–652 nm; and domed parts with a built-in lens.
- **Laser power does not limit the choice.** The lasers are believed
  to be under 1 mW (*unverified*), which a silicon photodiode takes
  easily. At silicon's highest responsivity, about 0.6 A/W at 848 nm,
  even 1 mW is only 0.6 mA, far inside the miniSMU's 180 mA. Any
  silicon photodiode gives about the same current, so another part
  would not change that.
- **What power does decide is the range.** Lower ranges are quieter
  (about 2 nA RMS on 25 µA, 27 nA on 650 µA, measured below), and
  streaming needs a fixed range, since autoranging drops samples. The
  contacted cell gave 0.6–2.1 µA under laser 2, which points to µW-level
  power at the sample. **Read each laser once on autorange** after
  mounting, then fix the lowest range that holds the brightest one.
- **Linearity with a tight spot:** a small spot concentrates the current
  in a tiny patch of the chip, and the response can bend before any
  range clips. If a laser is bright, run channel 2 at a few volts of
  reverse bias (e.g. −5 V; dark current is nA, negligible here), or
  raise the photodiode slightly for power readings. Knife-edge scans
  still need it in focus.
- **Mounting:** there is no focus axis, so the spot size at the
  photodiode depends on its height. Recess the can so the chip sits at
  the sample surface's height, or its knife-edge spot sizes describe a
  different focus from the maps. It has to sit on a corner every laser
  can reach within XY + AB travel, with a shielded twisted pair to
  channel 2 and enough slack to follow the stage.
- **The new stage's design** (the builder, 2026-10-28; built and on
  the machine 2026-10-29). The knife edges are two scalpel blades over
  the can, not the chip's own edges, which sit under the window below
  focus:
  - the can 35 mm from the AB centre along A; the chip inside it about
    1.5 mm towards B- of the can's centre;
  - one blade's edge along B (scans along A cross it) and one along A
    (scans along B), crossing over the chip, so one quarter of the chip
    is open: the quarter towards **A- / B-** as built (A+ / B- in the
    design of 2026-10-28). Not trimmed: two straight edges cross in a
    clean corner;
  - the blade along B sits **0.4 mm lower** than the one along A (their
    measured thicknesses). It is the one at the sample's height
    (confirmed as built, roughly, 2026-10-29), so focus and spot sizes
    along A (along the rows) are measured in the maps' focal plane; the
    B edge is 0.4 mm above it.
  - **Reaching it:** the photodiode is on the side that comes to the
    beam as A rises (the builder, 2026-10-28), so XY has to go about
    35 mm further in X than it does to centre AB under a laser. In the
    CAD, AB's centre is under laser 1 at about X 67, Y 84, and the
    photodiode at about X 96 with AB centred: 4 mm short of X's 100 mm
    end. `machine.toml` puts laser 1's AB centre at X 79.6, Y 71.3,
    which would ask for about X 109. Those absolute values were never
    checked (maps use only the differences between lasers, through the
    calibration), so which is right is open. AB adds margin either way:
    each mm of A above its centre saves a mm of X, and A can go up to
    35 (its safe limit).
  - **As built** (the builder, 2026-10-29): lasers 1-3 reach the open
    quarter, only just, all with X at or near its 100 mm end:

    | Laser | X | Y | A | B | Along A, B from its `xy_centre_mm` and AB centre |
    |---|---|---|---|---|---|
    | 1 | 100 | 70 | 33.2 | 19.3 | 36.1, +0.5 mm |
    | 2 | 99.7 | 79.3 | 30 | 10 | 36.6, +0.1 mm |
    | 3 | 100 | 80 | 28.7 | 7.6 | 36.2, +0.1 mm |

    The last column is (X - x_centre) + (A - 17.5) and
    (Y - y_centre) + (B - 17.5): where on the plate each laser met the
    quarter, by `machine.toml`'s laser positions. The three agree to
    0.5 mm (placed by eye, "roughly the same spot"), and 36 mm along A
    is the designed 35 mm plus the quarter's offset from the can's
    middle. So **`machine.toml`'s laser positions hold, and the CAD's
    (X 67 for laser 1) is the one that is off**. Laser 1 has the least
    room: X at its end and A 1.8 mm short of its 35 mm safe limit.
  - **The blades' corner, and laser 1's margin past it.** *Wrong way
    round, corrected 2026-10-30 (0.6.21, below):* the open quarter lies
    towards A- and B- of the corner on the carriage, which is larger A
    and B in the carriage frame, so the corner is at *smaller* A than
    where the lasers met the quarter. What follows was the reasoning
    then.
    `[photodiode] corner_ab_mm` estimates it 0.9 mm further (half the
    open quarter): (54.7, 18.6) on the carriage. Laser 1 then reaches
    only **0.7 mm past the A edge** (X 100, A 35), against 4.7 and
    5.3 mm for lasers 2 and 3. Enough for focus assist's ±0.5 mm
    passes if the estimate holds; commissioning finds the corner
    itself, and if laser 1 falls short, the mount moves 1-2 mm towards
    A- or the A edge is scanned with lasers 2 and 3 only.
- **The new stage, other changes** (the builder, 2026-10-29):
  - it sits **1 cm lower** than the old one, and lasers 1-3 were
    refocused by hand for it. So `spot_um` in `machine.toml` is out of
    date, and `xy_centre_mm` may be too (a beam that isn't quite
    vertical lands elsewhere 1 cm lower). Maps from different lasers
    may not line up until commissioning measures both again;
  - a **new test cell**, contacted by silver paint (dag) underneath
    rather than held by Kapton at its edges, with a new calibration
    file. `stdtest-redge.json` belonged to the old cell: the sync check
    needs a new window across a straight edge.

#### First readings on channel 2, 2026-10-29

`multilbic read`, no motion, each laser on its open quarter at the
positions above; files `~/cal/pd-*.json` on the Pi. Read 2 s after
lighting, so not warmed up. Powers are rough, from typical S1223-01
responsivities (about 0.3 A/W at 444 nm, 0.35 at 519, 0.45 at 652).

| Reading | Result |
|---|---|
| Dark, 0 V, autorange | 15.5-16.1 nA, scatter 27-44 pA: the SMU's offset or a little room light; no short, no noise |
| Laser 1 | -408 uA on the first lighting, then -463 uA at -5 V and -466.5 uA at 0 V: no saturation at 0 V, the laser rose 14 % between lightings. About 1.5 mW |
| Laser 2 | -7.36 uA, scatter 150 nA (warming). About 20 uW, 60 times weaker than laser 1, as the cell has always shown |
| Laser 3 | On autorange, -0.5 to -0.77 mA with one reading of +6.2 mA: clipping at the top of the 650 uA range and switching. On a fixed 15 mA range, -968 uA lit and +271 uA dark, the dark being the offset described below: **-1.24 mA**, about 2.8 mW |

- **For about an hour, channel 2 read high by about 1.7 % of the
  range's full scale, on every range, whatever the bias.** Dark
  readings, no light change, only the range and bias changed
  (2026-10-29, afternoon):

  | Range | Dark at 0 V | Dark at -5 V | Share of full scale |
  |---|---|---|---|
  | autorange (1 uA) | +15.9 nA | | 1.6 % |
  | 650 uA | +10.84 uA | +10.87 uA | 1.7 % |
  | 15 mA | +270.7 uA | +271.4 uA | 1.8 % |

  The same at 0 V and -5 V, so it is the measurement's offset, not
  current through the photodiode; the "dark current" of 16 nA is the
  1 uA range's share of it. Channel 2 also reports its voltage
  +0.27-0.29 V off (+0.274 V at 0 V, -4.712 V at -5 V), on every
  range. Channel 1 shows neither (its laser-off baselines are -0.4 to
  -20 nA on 25 uA, where 1.7 % would be 425 nA).
- **Checked by moving the photodiode to channel 1** (cell off, the same
  dark readings, 2026-10-29): channel 1 holds its voltage to 0.5 mV
  (-0.0005 V at 0 V, -4.9998 V at -5 V), and its offsets are tiny:

  | Range | Channel 1 dark, 0 V | -5 V | Channel 2, same photodiode |
  |---|---|---|---|
  | autorange | -0.47 nA | | +15.9 nA |
  | 650 uA | +25.9 nA | +40.2 nA | +10.84 uA |
  | 15 mA | +1.05 uA | +0.97 uA | +270.7 uA |

  So the offset and the voltage error were on **channel 2**, not the
  photodiode: about 250 times channel 1's. Under laser 3, channel 1
  on autorange read -1.028 mA at +0.42 V: the 1 mA current limit, where
  the SMU can no longer hold 0 V. Laser 3 needs a fixed 15 mA range on
  either channel.
- **The three lasers on channel 1**, the stage homed and sent to each
  laser's place by `read --at` (positions above), each laser on a fixed
  range with its own dark on that range, read 2 s after lighting:

  | Laser | Channel 1 | Range | Channel 2 earlier, its offset removed |
  |---|---|---|---|
  | 1 | -681 uA (clipped), then **-733 uA** | 650 uA, then 15 mA | about -477 uA (650 uA) |
  | 2 | **-6.46 uA** | 25 uA | about -7.8 uA (25 uA) |
  | 3 | **-1.211 mA** | 15 mA | -1.239 mA (15 mA) |

  Laser 3, both channels on 15 mA, agrees to 2 %: with its dark read on
  the same range, channel 2 measured right even with the offset.
- **Back on channel 2, the offset was gone.** The photodiode moved back
  to channel 2 and the cell stayed on channel 1, the wiring of the
  afternoon, and laser 1 was read at its place minutes after channel 1:

  | Laser 1 | Dark on that range | Lit, less dark |
  |---|---|---|
  | channel 1, 15 mA | +1.6 uA | -733 uA |
  | channel 2, 15 mA | +0.78 uA | **-739 uA** |
  | channel 2, 650 uA | +32 nA | -716 uA (near the range's top) |

  Channel 2's dark on autorange was -0.5 nA at -0.3 mV, against +16 nA
  at +0.274 V before. **Cause unknown.** Not the cell: the box was
  closed throughout, and the photodiode has no electrical connection to
  the cell. The wiring was the same as when the offset was there, so
  what changed is something the two swaps touched: how the leads sit
  in channel 2's terminals, or a state inside the SMU (its reset does
  not reboot it, so settings carry over between runs; SMUniversal's
  notes on this unit describe nothing like it). Laser 1 was then about
  -735 uA on both channels, so the -466 uA of the afternoon was low:
  the offset, or the hand-placed spot partly behind a blade edge.
- **What to take from it:** read the dark on the same fixed range as
  the laser, which also removes such an offset, and look at the voltage
  `read` reports: a channel at 0 V that reports more than a few mV off
  is in that state again. `commission` should check the same.
- **The open side was read the wrong way round (found 2026-10-30,
  fixed in 0.6.21).** Watching a run, the builder saw the spot cross
  the can's metal case, not a blade: every pass ran *away* from the
  blades, in A and in B. The carriage frame counts a point by the stage
  position that puts it under the beam, and a point further towards
  the stage's A- on the carriage has to travel further towards A+ to
  reach the beam: a quarter open towards A- as built is at larger A in
  that frame. `open_a`/`open_b` stay as the builder sees them ("-");
  `Photodiode.open_signs` turns them into the frame. The simulator took
  the same wrong convention, so it agreed and couldn't catch it.
  - So the run below crossed **the can window's far edges**, not the
    blades: its corner (60.239, 23.062) is that window corner, and its
    widths are that edge's, below the sample's height. The lasers'
    positions are each laser's view of the same window corner, so they
    hold against each other if the beams are near vertical; they stand
    until commissioning runs again.
  - The corner is an estimate again (`measured = false`): 1.8 mm back
    from the window corner along both, (58.44, 21.26), which puts the
    open quarter's middle where the light was found. Laser 1 then
    reaches 5.0 mm past it along A.
- **The servo doesn't put a laser back where it was (2026-11-04).**
  After the revolver screw was tightened, lasers 1, 3 and 5 commissioned
  in one run had moved 0.1-0.3 mm against each other since 2026-11-03,
  and an all-six run half an hour later, nothing touched, moved them
  again by up to 0.12 mm, each its own way (not homing, which would
  move them all alike). A direct test (`servo_position.py`, homed once):
  laser 3's spot half over a blade edge, where the current changes by
  25-70 uA per um, then the servo to laser 1 (120 deg) or laser 2
  (60 deg) and back, ten times, the edge scanned again after each:

  | Along | Laser 3 held, servo still | After each servo return |
  |---|---|---|
  | A | spread 0.1 um | **spread 44 um**, 20-185 um from the first landing |
  | B | spread 0.0 um | **spread 20 um**, 3-68 um from it |

  - The stage, the laser and the photodiode hold to a tenth of a um; the
    revolver lands each laser within about +-0.1 mm, differently each
    time, from either side. That is the run-to-run scatter of every
    laser position, and it limits how well maps from different lasers
    line up, whatever `machine.toml` says.
  - **Decided: placing from the photodiode** (0.6.43): every run
    locates each laser right after selecting it and places its map from
    that ([run](run.md)). In the simulator, with the servo landing three
    lasers 34-139 um off, their maps spread about 100 um placed from
    `machine.toml` and under 25 um located (the measure's own scatter is
    about 10 um a laser).
  - Laser 2's output swung from -11 to -48 uA between runs the same
    afternoon (one commissioning failed on it), the 5 V supply again.
- **The servo moves on its own while powered (2026-11-05).** Maps
  located on the photodiode still didn't line up, so the spot was
  watched on a blade edge for minutes at a time (`servo_creep.py`,
  `servo_ab.py`; the photodiode reads 13-70 uA per um there):

  | Test | What moved | The edge |
  |---|---|---|
  | Laser 3, revolver screws eased, edge tracked by the stage, then three servo swings away and back | stage | after each return, 60-106 um over 2 min, in jumps of 8-40 um |
  | B: laser 4 parked half over the edge, stage still, then two swings | nothing | jumps of 7-24 um, all one way, at random times for minutes; 20 s apart to over a minute |
  | A: laser 4, edge tracked by the stage for 4 min, servo not moved | stage | drift of -12 um, no jumps |

  - With nothing else moving, the spot jumps only while the servo is
    powered and holding an angle: its controller corrects itself now and
    then (the builder's idea), each time a few um of beam. Moving the
    stage and reading the photodiode don't do it (test A).
  - **Decided: release the servo after each turn** (firmware 2.1.0,
    0.6.44); the gearbox holds the revolver.
  - **Released, it holds** (2.1.0 flashed, the same tests again,
    `servo_still.py` and `servo_creep.py`):

    | Test | Powered (2.0.0) | Released (2.1.0) |
    |---|---|---|
    | Laser 4, stage still, 60 s before any swing | jumps to +11, then +31 um | within 0.3 um |
    | Laser 4, stage still, 2 min after each of two swings | jumps of 7-24 um, up to +54 um | under 2 um, no jumps |
    | Laser 3, edge tracked by the stage, 2 min after each of three swings | +60, +62, +106 um | +7, +11, +4 um (the tracking's own scatter is about +-10 um a point) |

    - Each selection still lands the laser somewhere new: laser 4 at
      -34 and -42 um from where it was parked, laser 3 at +7, +21 and
      +31 um. That is what locating on the photodiode after each
      selection measures, and now the laser stays there for the map.
  - **Six lasers within 60 um** (two runs, each laser located on the
    photodiode, the servo released; `20261105T142736Z` and
    `20261105T144808Z_std_test_v2-corner`). The cell's two edges in
    each laser's map, from the rows and columns well inside the patch:

    | Laser | Edge along B (u), run 1 | run 2 | Edge along A (v), run 1 | run 2 |
    |---|---|---|---|---|
    | 1 | 0.417 | 0.394 | 0.172 | (none) |
    | 2 (dim) | 0.215 | 0.377 | (none) | 0.122 |
    | 3 | 0.410 | 0.385 | 0.070 | 0.079 |
    | 4 | 0.272 | 0.337 | 0.138 | 0.146 |
    | 5 | 0.378 | 0.368 | 0.172 | 0.172 |
    | 6 | 0.372 | 0.361 | 0.139 | 0.140 |
    | **Spread** | 200 um | **57 um** | 100 um | 93 um |

    - The last located run with the servo powered spread 370 um along u
      and 150 um along v.
    - Lasers 1, 3, 5 and 6 repeat within 25 um along u, and 3-6 within
      10 um along v. Laser 4 moved 65 um along u between the runs, and
      laser 2 (about 30 times dimmer, located with full sweeps) 160 um.
    - Laser 3 sits 60-100 um below the others along v in both runs: a
      fixed offset, perhaps its beam's tilt between the upper blade
      (0.53 mm above the cell) and the cell. Its edge along A is near
      the patch's start, from only 4-9 columns.
    - All six were found 0.1-0.4 mm from `machine.toml`, differently in
      each run (the servo's landing); that is what the locate step is
      for.
    - The serpentine shift was negative for 3 of the 12 maps (laser 3
      -87 um in run 1; lasers 1 and 5, -196 and -68 um, in run 2;
      +117 to +156 um for the rest). Those maps' two directions still
      agree after it (their edges' spread is no wider), so the timing
      itself changed for those maps, by about 40 ms at 4 mm/s.
- **Marlin's reply to a row's `M400` sometimes comes late
  (2026-11-05).** The flipped maps above, fitted from the cell's edge
  in each direction without the alignment, really had forward rows on
  the far side of reverse ones. The samples' dating was clean (no lost
  samples, no step in the stamps or the clock map). What changed was
  the time from each row's `G1` being sent to the `ok` of its `M400`,
  beyond the modelled move:

  | Map | On time | Late rows | Late by | Flip that predicts | Flip from the edge |
  |---|---|---|---|---|---|
  | Laser 3, run 1 | rows 0-3 | 4-29 | 27 ms | 219 um | 211 um |
  | Laser 1, run 2 | none | all (row 1 by 19 ms) | 39 ms | 315 um | 316 um |
  | Laser 5, run 2 | rows 0-2 | 3-29 | 25 ms | 198 um | 203 um |

  - On time it is 93-94 ms at 4-5 mm/s and 95.5 ms at 1 mm/s, steady to
    half a millisecond in each file, in 72 run files since 2026-10-23.
    About one map in six has a late stretch, back to 2026-10-28.
  - The late replies all came about 90 ms after one of the miniSMU's
    100 ms bursts of samples arrived, just before the next; on time
    they came anywhere between. The rows are paced by those bursts
    (each waits for its samples), so a map keeps the same phase and
    stays late once it is. Whether Marlin or the Pi holds the reply
    back is not known.
  - **Decided: place late rows from the send** (0.6.47). The maps of all
    four six-laser runs of the day then give shifts of +110 to +157 um,
    none negative, and each map's two directions meet on the cell's
    edge.
- **Six lasers repeat within 20 um (2026-11-05, 0.6.47).** A third
  located map (`20261105T154210Z_std_test_v2-corner`), the cell's edges
  as before:

  | Laser | Edge along B (u), run 2 | run 3 | Edge along A (v), run 2 | run 3 |
  |---|---|---|---|---|
  | 1 | 0.394 | 0.376 | (none) | (4 columns) |
  | 2 (dim) | 0.377 | 0.378 | 0.122 | 0.124 |
  | 3 | 0.385 | 0.374 | 0.079 | 0.070 |
  | 4 | 0.337 | 0.334 | 0.146 | 0.162 |
  | 5 | 0.368 | 0.369 | 0.172 | 0.173 |
  | 6 | 0.361 | 0.362 | 0.140 | 0.119 |
  | **Spread** | 57 um | **44 um** | 93 um | 103 um |

  - Along u every laser repeated within 18 um, and five agree within
    16 um; laser 4 is 35 um short of them in both runs.
  - Along v each laser repeated within 2-21 um, but they spread
    100 um: laser 3 lowest (0.07), 2 and 6 at 0.12-0.14, 4 and 5 at
    0.15-0.17. Fixed offsets per laser, not drift.
  - Lasers 1 and 4 had late replies on 27 rows each; placed from the
    send, their shifts were +120 and +133 um, as the cell's edge says.
    Laser 6's alignment chose +82 um where its edge says +137 um, as in
    run 1 (its row pairs split between about 80 and 155 um).
  - **That was the mains removal** (0.6.49). Laser 6's rows had no 50 Hz
    to speak of; the fit over each whole row put it there, the cell's
    1 mA edge leaking about 1 % into the sines. Fitted where the row is
    flat instead, every map of the day aligns at +110 to +157 um and
    laser 6's at +115 to +132; its edge spread over rows halved, 36 to
    19 um.
  - **Laser 3 "lowest along v" was not real** (0.6.50). Measured again
    with the line-up's edge finding (`run/lineup.py`), the edge along A
    of lasers 1-3 sits 0.05-0.07 mm into these patches, one or two
    50 um rows from their start: too few points on one side to fit, and
    now reported as not found. Laser 2, dim, was found among the others
    along u (0.372-0.375 mm). The line-up centres its patch on the cell's
    corner, with 25 um rows, for this. **The reference is laser 3 since
    0.6.50**, laser 2 giving a twentieth of the others' light.
- **The six-laser map, and lasers 1-3 moved (2026-11-03).** A
  1.5 x 1.5 mm patch at the cell's corner with all six lasers
  (`20261103T171854Z_std_test_v2-corner`, 0.6.29): lasers 4-6 lined up
  to 0.1 mm, lasers 1-3 did not, by up to 1 mm. Commissioning all six
  again (`20261103T175926Z_commission`) found lasers 1-3 moved since
  2026-10-30 by what the map showed, and 4-6 not:

  | Laser | Moved since 2026-10-30 (photodiode) | Map shift against laser 5 |
  |---|---|---|
  | 1 | -0.04, -0.49 mm | +0.04, -0.46 mm |
  | 2 | +0.46, +0.90 mm | +0.49, +0.88 mm |
  | 3 | +0.25, +0.31 mm | +0.25, +0.25 mm |
  | 4 | +0.06, -0.06 mm | +0.06, -0.10 mm |
  | 5 | -0.03, 0.00 mm | (reference) |
  | 6 | +0.03, -0.03 mm | +0.01, -0.06 mm |

  - **The photodiode and the cell agree** to a few tens of um: the
    positions it measures are the maps' positions. The A travel (lasers
    1-3 reach the photodiode with A 12-17 mm from where they map) and
    the height don't show.
  - **Lasers 1-3 moved, each its own way**: not one shift of the
    revolver, so their mounts. They were commissioned at 16:46 on
    2026-10-30; lasers 4-6 were refocused by hand after it and
    commissioned at 18:13, and those are the ones that held. Handling
    in the box can move a laser by half a millimetre: **commission all
    six after any work in it** (18 min).
  - **Laser 2 is fading**: -47, -33, now -17.5 uA on the photodiode
    (2026-10-30 twice, 2026-11-03). On the cell its map had a 33 uA
    step against 600-700 uA for the others. Its power cable or
    connector, or the laser.
  - Laser 2 also saw the cell's corner about 0.5 mm from where it was
    calibrated with laser 2 on 2026-10-30: most of that is laser 2
    having moved (+0.46, +0.90 mm), which `machine.toml` now carries;
    calibrations record laser 2's position, so they follow.
- **The laser supply's trimmer (2026-11-03).** All six lasers hang on
  one LM317 with one trimmer, fed from the SKR's 5 V, which also feeds
  the servo. An LM317 needs about 3 V between input and output to
  regulate, which leaves about 2 V: enough for the red and infrared
  diodes, not for green (laser 2) or blue (laser 1), which need about
  3.5-5 V. Turning the trimmer up took laser 2 from 7.5 to 11 uA on the
  photodiode, live with the box open, and no further: the ceiling. Read
  after it, box closed (`~/cal/reads/pd-all-20261103-trimmer.json`,
  2 s each, no warm-up), against the commissioning that afternoon (after
  warm-up and passes):

  | Laser | Commissioning | After the trimmer | Change |
  |---|---|---|---|
  | 1 (444 nm) | -0.678 mA | -0.774 mA | +14 % |
  | 2 (519 nm) | -17.5 uA | -29.3 uA | +68 % |
  | 3 (652 nm) | -1.207 mA | -1.222 mA | +1 % |
  | 4 (676 nm) | -1.493 mA | -1.563 mA | +5 % |
  | 5 (785 nm) | -1.309 mA | -1.324 mA | +1 % |
  | 6 (848 nm) | -1.997 mA | -2.013 mA | +1 % |

  - The red and infrared lasers didn't follow the trimmer: their
    modules hold their own current. Blue and green did: they are
    starved by the 5 V. Laser 2's figure is early in its lighting, and
    it fades within a run, so part of its +68 % is that.
  - The fix for lasers 1 and 2 is hardware: a laser supply above 5 V, or
    a low-dropout constant-current driver for those two. The setting
    stays where it is meanwhile.
  - **Laser 2 over 3 minutes from lighting** (box closed, on the open
    quarter, `~/cal/reads/pd-l2-3min-20261103.json`): it **rises**,
    -27.6 uA in the first 10 s, -38.0 at 1 min, -42.1 at 2 min, -44.5 at
    3 min and still climbing about 0.4 uA per 10 s. Readings scatter
    1-3 uA with spikes of up to 10 uA. So the 60 s warm-up leaves it at
    about 85 % of its 3-minute level, and a laser 2 map gets brighter
    down its rows. The falls within the commissioning runs of 2026-10-30
    (-47.7 to -33.4 uA) are not this: *unexplained*, maybe where on the
    open quarter each was read, since the first and last readings are at
    different places.
- **The patch again, after commissioning (2026-11-03,
  `20261103T182248Z_std_test_v2-corner`, 0.6.30).** Edge positions in
  the patch (mm):

  | Laser | Edge along B (u, along the rows) | Edge along A (v, across) |
  |---|---|---|
  | 1 | 0.56 | about 0-0.05 (faint) |
  | 2 | 0.45 | too weak to fit |
  | 3 | 0.43 | 0.115 |
  | 4 | 0.33 | 0.122 |
  | 5 | 0.39 | 0.135 |
  | 6 | 0.36 | 0.112 |

  - Across the rows lasers 3-6 now agree to 0.02 mm (were up to 1 mm
    apart). Along the rows to 0.1 mm: that direction rests on the
    scan's timing correction at 4 mm/s, which the sync check (step 3)
    measures.
  - Laser 1 is still about 0.17 mm off along the rows. Laser 2 gives
    about 10 uA on the cell now, too little for its edge across rows.
  - **The gaps** (4.6 % of the pixels empty) are the stream's skips:
    every row had six 7 ms jumps in the device stamps, about every
    100 ms, as on 2026-10-19 (below). At 4 mm/s that is 28 um, 2-3 empty
    10 um pixels. Pictures now fill runs of up to 4 empty pixels along a
    row (0.6.31); the data keeps them.
- **Lasers 4-6 commissioned (2026-10-30, `20261030T181328Z_commission`,
  0.6.27)**, box closed, against the measured corner, written to
  `machine.toml` (0.6.28):

  | Laser | Power | 10-90 % lower / upper blade | `xy_centre_mm` moved from by eye |
  |---|---|---|---|
  | 4 (676 nm) | -1.50 mA | **98.4** / 83.0 um | -543, +924 um |
  | 5 (785 nm) | -1.31 mA | **71.3** / 84.0 um | -361, +218 um |
  | 6 (848 nm) | -2.00 mA | **74.9** / 94.6 um | +73, +295 um |

  - Laser 4's light was again found on the blade (-101 uA against
    -1.5 mA): the ±2 mm coarse sweep saw the full light anyway, and a
    pass that reached the 650 uA range's limit went again on 15 mA.
  - Up minus down 7-29 um. Lasers 5 and 6 are wider on the upper blade,
    unlike 1-3.
  - **Bright on the chip, 1.3-2.0 mA**, with spots under 100 um: the
    response may bend before any range clips (linearity, above). The
    edges don't depend on it, the powers may; a read at -5 V would tell.
    The window's idle readout, held to 1 mA, shows them as `(limit)`.
  - All six lasers now have a measured position and spot.
- **Laser 4's first tries (2026-10-30).** At its placeholder it lit
  the photodiode at -4.5 uA, the spot mostly elsewhere; refocused by
  the builder, -560 uA. Then the edge along B (passes along A) came out
  clean (A 58.140, 86 um), but the light had been found on the blade
  along A itself, about 0.9 mm off along B: the coarse pass along B
  started at half light and fell to dark within 0.1 mm, with no full
  light to fit from. Since 0.6.27 the coarse sweep spans ±2 mm round
  where the light was found (the builder's suggestion), then a medium
  sweep, then the fine passes; a pass that clips steps the range up.
  Lasers 5 and 6 were found with an IR card (laser 6 12 mm from its
  placeholder).
- **Commissioned across the blades (2026-10-30,
  `20261030T164634Z_commission`, 0.6.22)**, lasers 1-3 at 0 V, box
  closed, written to `machine.toml` (0.6.23):

  | Laser | Power (first -> end) | 10-90 % lower / upper blade | Corner seen (A, B) | `xy_centre_mm` moved |
  |---|---|---|---|---|
  | 1 | -777 -> -703 uA, 15 mA | **59.4** / 48.4 um | 58.498, 21.021 | -70, +6 um |
  | 2 | -47.7 -> -33.4 uA, 650 uA | **39.3** / 21.8 um | 58.569, 21.016 | reference |
  | 3 | -1.215 -> -1.213 mA, 15 mA | **30.9** / 19.7 um | 58.563, 21.053 | -5, +37 um |

  - The corner is 0.25 mm from the estimate, and the three lasers see it
    within 0.07 mm. Up minus down on each edge: 6-13 um, the backlash.
  - **The refocusing by eye held**: lasers 1 and 2 are near their old
    65 and 41 um, laser 3 much sharper than its 244 um.
  - **Every spot is narrower on the upper blade**, 0.4 mm above the
    sample's plane: the waist is above the plane, or the spot is
    astigmatic. Focus assist tells which: turning the focus moves the
    narrowest point between the blades if it is height.
  - The positions moved at most 70 um from the window-corner run, so
    the beams are near vertical, and laser 1's 1.3 mm from yesterday's
    `machine.toml` stands.
  - **Laser 2 fell 30 % within its run**, as in the run before (laser 1
    10 %, laser 3 steady): its power cable or connector is suspect.
  - No channel-2 offset this time.
- **Commissioned (2026-10-30, `20261030T140929Z_commission`)**, lasers
  1-3 at 0 V, X to 103, written to `machine.toml` (0.6.19), replaced by
  the run above. **The can window's edges, not the blades (above):**

  | Laser | Power | 10-90 % along A / B | Corner seen (A, B) | `xy_centre_mm` moved |
  |---|---|---|---|---|
  | 1 | -699 uA, 15 mA | 238 / 271 um | 59.711, 24.342 | -0.53, +1.28 mm |
  | 2 | -36.9 uA, 650 uA | 272 / 318 um | 60.239, 23.062 | reference |
  | 3 | -1.224 mA, 15 mA | 254 / 303 um | 59.844, 23.096 | -0.40, +0.04 mm |

  - The corner is laser 2's view, 0.5 mm from the estimate by eye, and
    now `measured`. Up minus down on each edge: 5-33 um, the backlash.
  - **Lasers 1 and 2 are out of focus**: 65 and 41 um on the old stage
    (the cell's edge, 2026-10-23), about 250 um now, after the stage
    went 1 cm lower and they were refocused by eye. Every B edge (the
    upper blade, 0.4 mm higher) is wider, as defocus would make it.
    Focus assist (step 6) is for this.
  - **Laser 1 moved 1.3 mm along Y against laser 2**: the lower stage
    and the refocusing, presumably. Calibrations use laser 2, so laser 1
    maps would have been that far off. *Unverified on the cell*: a
    small map with lasers 1 and 2 would show it.
  - **Laser 2 is about 6x yesterday's** (-6.5 uA), after the builder
    fixed a loose laser power cable, but fell from -45.9 to -36.9 uA
    within its own run: the connection may still be loose.
  - **Channel 2 was in the offset state again** (+0.28 V at 0 V) from
    the start, after the photodiode's leads were re-secured (they had
    come off during a homing, which made the first try find no light).
    The same-range dark removed it from the powers; positions are not
    affected.
- **A dark reading counts only on the range of the reading it is
  taken from.** Runs and `commission` read on fixed ranges with a
  laser-off baseline on the same range. `read` on autorange takes the
  dark on the 1 uA range and the laser on a larger one.
- **Negative**, as the cell reads on channel 1: the photodiode is wired
  the same way round.
- **0 V is fine** for laser 1 (same reading at -5 V). Whether channel
  2 really sits at +0.27 V, or only reports it, is open: a photodiode
  at +0.27 V would pass only nA, so it changes nothing here.
- **The ranges differ by laser**: 25 uA for laser 2, 650 uA for laser
  1 (1.4x headroom) or 15 mA, 15 mA for laser 3. `commission` picks
  channel 2's range per laser.
- **Laser 3 is beyond autorange's 1 mA limit**: the window's live
  readout marks a reading at that limit.
- **A power reading straight after lighting is good to about 15 %**:
  `commission` reads power after the warm-up.
- **Absolute EQE** would need a calibrated photodiode (for example a
  Thorlabs FDS100-CAL), which RS does not sell. The S1223-01 gives
  relative spectral response.

### Streaming, measured 2026-10-19

Report `bench-results/20261019T180307Z_smu_real.json` (commit
`fe17a93`), plus a read-speed experiment with the output off.

- **Packet format**: `1,1792432988369,7.1335e-04,-1.5365e-09,0`, which is
  channel, timestamp, volts, amps, and a **fifth field**, already on
  1.4.6. It read `0` at nA currents, so it is probably the range index;
  *unverified*. The timestamp is Unix time in **whole milliseconds**,
  set by `set_time()`.
- **Delivered rate is not the requested rate, and not repeatable.** 100
  Hz requested gave 100.7 Hz in one run and 114 Hz in the next; 500 gave
  500 and 567; 1000 gave 938 and 1194. The device's timestamps have to
  be the reference, never the requested rate.
- **The instrument can stream above 1 kHz**: 1194 Hz on one channel,
  read cleanly for 20 s.
- **Reading one line at a time cannot keep up on the Pi.** `minismu_py`
  reads each packet with pyserial's `readline()`, which fetches one byte
  per system call. In a bare loop that reached about 750 packets/s, and
  the backlog grew 0.3 → 1.1 s in 20 s at 1000 Hz. Through `SmuStream`
  (more per-sample work), even 500 Hz fell up to 1.7 s behind over
  60 s. **Reading in bulk** (everything waiting, split into lines) kept
  up at 1190/s with a flat backlog. `SmuStream` reads in bulk since
  0.1.5.

**With the bulk reader** (0.1.5, report
`bench-results/20261019T181449Z_smu_real.json`, commit `c0da98f`):

| Requested | Delivered (device clock) | Step jitter | Repeated stamps |
|---|---|---|---|
| 100 Hz | 100.0 Hz | 0.31 ms | 0 |
| 250 Hz | 250.0 Hz | 0.49 ms | 0 |
| 500 Hz | 504.0 Hz | 0.51 ms | 0 |
| 1000 Hz | 1008.6 Hz | 0.65 ms | 332 of 4900 |
| 2000 Hz | **1408.6 Hz**, the instrument's ceiling | 0.92 ms | 2533 of 6930 |

- **Two channels** at 500 Hz each: 563 and 500 Hz, no parse errors, and
  both stopped cleanly.
- **Confirmed 2026-11-03: the stamps saw-tooth, the samples are all
  there.** Every row of a map at 800 Hz had 480 samples in 599 ms (the
  rate kept exactly); between jumps the stamps advanced 1.177 ms a
  sample instead of 1.25, then jumped about 6 ms, six times a row. Away
  from a straight line through them, the stamps sit -1.7 to +4.7 ms off.
  So the instrument measures evenly and its stamps lag and catch up:
  dated by stamps, samples sit up to ~12 um off along a row at 4 mm/s
  and leave 2-3 empty 10 um pixels at each jump. Since 0.6.35 samples
  are dated by count ([scan](scan.md#position)).
- **The sync check on the new cell (2026-11-04,
  `20261104T115342Z_sync_std_test_v2-corner`, 0.6.32)**, laser 3, the
  cell's edge along B, window 0.6 x 1.0 mm, dated by stamps (files from
  before 0.6.35 can't be dated by count across rows: the stream between
  rows wasn't kept):

  | Pass | Forward (spread) | Reverse (spread) | Shift from edges / alignment |
  |---|---|---|---|
  | 1 mm/s | +17.4 um (0.8) | -18.3 um (3.1) | 32.1 / 36.1 um |
  | 4 mm/s | +80.2 um (18.7) | -72.5 um (2.6) | 151.5 / 142.6 um |
  | 5 mm/s | +112.2 um (10.0) | -111.4 um (6.0) | 215.5 / 223.2 um |

  - L = 22.6 ms with an A backlash of -13 um, which can't be: one lag
    doesn't fit all speeds (17, 20, 22 ms at 1, 4, 5 mm/s), as a
    saw-tooth in the stamps would make it. 5.7 um RMS left.
  - The maps' alignment agrees with the edges to about 9 um at 4 and
    5 mm/s; 5 mm/s scatters no more than 4 mm/s.
  - Step-and-measure: spot 21 um (10-90 %); drift over the 16 min
    -8.7 um.
  - Dated by count within each row only (one line per 0.3-0.6 s row,
    which catches the saw-tooth's phase): L 15.9 ms, backlash +4 um,
    8.0 um RMS, the spreads mixed. Not conclusive; the next check, with
    the stream kept between rows, dates by count over whole passes.
- **The sync check again, the stream kept whole (2026-11-04,
  `20261104T135122Z_sync_std_test_v2-corner`, 0.6.36)**, the same edge,
  window and laser:

  | | Dated by count | Stamps as recorded |
  |---|---|---|
  | L | **14.9 ms** | 19.9 ms |
  | A backlash | **+4.0 um** | -8.2 um |
  | Lines leave | 4.0 um RMS | 4.8 um RMS |
  | Alignment / edges, 4 mm/s | 118.3 / 114.9 um | 133.5 / 132.8 um |
  | Alignment / edges, 5 mm/s | 141.8 / 140.2 um | 204.8 / 197.4 um |
  | Row spread, 4 mm/s (fwd / rev) | 9.3 / 7.2 um | 2.9 / 9.8 um |
  | Row spread, 5 mm/s (fwd / rev) | 21.3 / 14.5 um | 7.4 / 17.7 um |

  - **Dated by count, the timing holds together**: a positive backlash,
    one lag that fits better, and the maps' alignment within 2-3 um of
    the edges at both speeds. Both sessions dated by count gave L of
    15-16 ms and a backlash of +4 um; by stamps the backlash came out
    negative both times. Count dating stays.
  - **The row spreads didn't shrink**, but this session the reference
    itself moved: step-and-measure before and after differ by -18.1 um
    with a 13.6 um spread across rows (-8.7 and 2.9 um in the morning),
    and the forward rows sit 22 um off at zero speed. With 5 rows a
    direction that noise swamps the comparison. *Unverified*: what
    moved (16 min with laser 3 on, the stage, the cell).
  - **Decisions:** `ab_backlash_mm` stays 0 (4 um is within the noise).
    The default speed stays 4 mm/s: at 5 mm/s the rows scatter more
    this time. A hardware marker (option C) is not needed for now: the
    alignment matches the edges to 2-3 um.
- **Bunching, not loss.** At 500 Hz and above, about every 100 ms the
  stamps skip 5–8 ms, then catch up with a burst of repeated stamps. The
  average rate is kept, so samples are not lost. That suggests the
  instrument stamps a packet when it **sends** it rather than when it
  measures, which would put several ms of timing error on samples near
  each skip (10–15 µm at 2 mm/s). *Unverified*: checking it needs a
  known light edge, e.g. the channel-2 photodiode.
- **Clocks**: over 60 s at 500 Hz, the instrument's clock ran
  **+306 ppm** against the Pi's (18 ms per minute). Arrival latency,
  above the fastest packet: median **52 ms**, max **109 ms**, with no
  growth. A sample's time has to come from its device stamp, mapped
  through a tracked offset and drift. When it arrived says little.
- **Autoranging drops samples while streaming** (first real maps,
  2026-10-21, runs `20261021T174652Z` and `20261021T175325Z`, laser 2 on
  a contacted cell in the cardboard box). The cell gave 0.6-2.1 uA,
  right across the 1 uA / 25 uA boundary. On autorange the stream's own
  stamps showed gaps of 10-15 ms, 91 % of them exactly where the current
  crossed 1 uA (1,401 gaps, 1,904 crossings in 12 rows), and the
  delivered rate fell from 400 to ~200 Hz. The Pi was not behind
  (arrival delay under 50 ms throughout). With the lead off, nothing
  crossed and the rate held at 400 Hz. So scans fix the range
  (`run --current-range`, default 25 uA) and stop if it clips.
- **Noise at 0 V, channel 1 open** (nothing connected; reports
  `20261019T181817Z` and `20261019T181857Z`, back to back) is
  repeatable: **14.3 and 14.8 nA RMS**, p-p ≈ 53 nA, on the auto and
  1 µA ranges; 15.8 nA on 25 µA; 32 nA RMS around a **+94 nA offset**
  on 650 µA.
- **It is mains pickup.** At 1 kHz, **89 % of the noise power is at
  50 Hz** (± 2 Hz), and the next strongest line is 150 Hz. Open leads are
  an antenna, so this is not the instrument's own floor. Against stream
  rate: 100 Hz gives 4.3 nA RMS (43 nA p-p), and 250–1000 Hz give
  14–15 nA. Sampling at 100 Hz lands on the same few points of each
  50 Hz cycle, which hides much of it.
- **With a cell contacted on channel 1** (2026-10-20, reports
  `20261020T123224Z` and `20261020T123445Z`, plus the spectrum check):

  | | Lights on | Lights off, stage covered |
  |---|---|---|
  | background current | −165 µA (−104 µA an hour earlier) | **−0.83 µA**, drifting −0.79 to −0.89 µA |
  | noise, autorange / 650 µA | 1.7 µA RMS, 8–9 µA p-p | **0.12 µA RMS**, 0.6–0.9 µA p-p |
  | slow drift, below 5 Hz | 89 % of noise power | 81 %, strongest 0.2–0.7 Hz |
  | 50 Hz mains | 0.1 % | 17 % |
  | 100 Hz light flicker | 8 % | 0.1 % |

  - The cell's low impedance removes most of the 50 Hz pickup that open
    leads had.
  - With lights on, the fixed 1 µA and 25 µA ranges saturate (0.6 mA
    spikes): those rows are invalid. Autorange and 650 µA are fine.
  - Dark, without the drift and 50 Hz, about **20 nA RMS per sample** is
    left, and a few nA once averaged over a pixel.
  - **The drift is the problem.** At 2 mm/s a 1 mm feature passes in
    0.5 s, around 2 Hz, the same band as the drift, so filtering it out
    would remove the map too. Whether the −0.8 µA and its drift are
    residual light (monitor, gaps in the cover) or the cell still
    relaxing after the lights went off is not known; a longer wait in
    the dark would tell. See D8 in the [plan](plan.md#decisions).
- The one quiet run (1.5 nA RMS, 18:03) was the only one read through
  the old per-line reader, which could not keep up. Why it was quieter
  is not known: possibly the instrument averaging longer while it waited
  to send, possibly the leads lying differently.
- **What this means for scanning**:
  - mains will dominate nA-level signals unless dealt with;
  - a cell connected instead of open leads should pick up much less
    (next measurement: a contacted cell, lights on and off. A covered
    cell is not possible, because contacting needs the top surface);
  - because raw samples are kept with their timestamps, a 50 Hz (and
    harmonics) notch can be applied along each row before binning, or a
    pixel's averaging window made a whole number of 20 ms cycles. With a
    cell connected, 50 Hz is minor; slow drift is the real limit (below);
  - shielded or twisted leads and the planned enclosure help at the
    source. The mains frequency here is **50 Hz**.
- **Two channels**: stopping one channel's stream while the other still
  streamed made the library wait for silence and raise, leaving channel 2
  streaming with its output on. Fixed in `SmuStream.stop()` (commit
  `fe17a93`), which turns every channel off first. Rates read through
  the per-line path under-delivered (536 / 407 Hz of 500), which the
  bulk reader should fix too.
- **Noise at 0 V**, about 1 kHz, default oversampling, channel 1 with
  *whatever was connected at the time (not recorded)*:

  | Range | Mean (offset) | Std. dev. | Peak-to-peak |
  |---|---|---|---|
  | auto | +0.04 nA | 1.5 nA | 5.5 nA |
  | 1 µA | +0.2 nA | 1.5 nA | 5.5 nA |
  | 25 µA | +3.3 nA | 2.1 nA | 10.6 nA |
  | 650 µA | +92 nA | 27 nA | 150 nA |

  About **1.5 nA RMS per sample** on the low ranges. An nA-level LBIC
  signal needs averaging over samples per pixel, or more oversampling
  (fewer samples per second). The load was not recorded for this run;
  the open-lead runs below were.

### Is it the fastest SMU available?

For one reading at a time, SMUniversal's fleet data shows a tie:
B2901A 5.7 ms, miniSMU 6.0 ms, the Keithley 2600-series and GSM-20H10
12–14 ms, the rest 35–77 ms. At 6 ms per reading and 2 mm/s that is a
point every 12 µm, which is not good enough. The miniSMU's real advantage
is streaming, nominally up to 1 kHz, which at 2 mm/s is a sample every
2 µm, and the instrument was measured streaming at up to ~1.2 kHz
(below). The bench instruments' buffered, triggered acquisition was not
compared. They live on another bench and the miniSMU is already
installed here.

## USB at boot

On both bench days (2026-10-19 and -20) the laser Xiao and the miniSMU
were **missing after the Pi booted**: the kernel made no attempt to
connect them and logged no error. The SKR and the TFT's FTDI adapter
came up normally each time. All four are on the Pi's own ports (the
Xiao on port 2, the miniSMU on port 4) or on a hub off port 1.

What was found out (2026-10-20):

- **The miniSMU was simply switched off.** It is not a bug: switch it on
  before starting the software.
- **The Xiao is the real case**, and it is **intermittent**:
  - On the failing mornings it came back only when its cable was
    replugged. The 20 Oct failure followed a cold start (the Pi was off
    at the wall overnight), so it is not about reboots.
  - No under-voltage in any boot the journal keeps.
  - The Xiao has no external power; only the servo and lasers do. With
    its USB unplugged and that supply on, its 3V3 pin reads **0.3 V**: a
    small leak back through the signal lines, probably too little to
    block a clean reset by itself.
  - Two cold starts that same day both brought it up normally, one of
    them with the supply on a minute before the Pi. So power order alone
    does not explain it. A supply left on for hours is untested.

**The fix is a safety net, not a cure:** `deploy/pi/usb-check.sh`, run
as a root service at every boot. If the Xiao has not appeared after 15 s,
it switches the Pi's USB power off and on with `uhubctl` (the same as a
replug, all ports together on a Pi 4), then checks again. It logs every
boot (`journalctl -t multilbic-usb-check`), so the next failure is
recorded with what else was present. Installed and a forced cycle
verified on 2026-10-20 (the Xiao was back 7 s later); the real
missing-at-boot path waits for the failure to recur. Install steps are in
[`deploy/pi/`](../deploy/pi/README.md). If the log shows it failing
often, the hardware option is 1–10 kΩ resistors in series on the
Xiao's signal lines.

## TFT35

Wired over USB-TTL, with no current role. Its backlight could disturb
measurements. Agreed direction: leave it out of the first version, then
make it a touch pendant for jogging during alignment, dark during scans
(Phase 7).
