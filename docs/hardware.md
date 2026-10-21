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
  planned fix (small hardware change, owed).
- **XY and AB move the sample the same ways** (bench, 2026-10-21,
  laser 2 on a mark; as the operator looks at the stage): **+X and +A
  move the sample up, +Y and +B move it right**, and both stages home to
  the bottom-left, like the first quadrant of a graph. So `x_along =
  "+A"`, `y_along = "+B"` in `machine.toml`.
  - Since the sample moves under a fixed spot, raising A brings the
    part of the sample *below* the spot under it. A sample therefore
    extends down and to the left of the corner calibration uses: the
    **top-right corner**, as seen by the operator (the old script asked
    for the top-right corner too).
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
is now **version 2.0.0** (Phase 2). Its protocol is in
[devices](devices.md#laser-board-protocol-20). Pins and angles are
unchanged: laser enables on pins 1, 2, 3, 4, 5, 8, servo on pin 9, and
pins 0, 6, 7 and 10 free.

What changed from the 1.x sketch:

- 1.x replied in free text (`Servo moved to: 90`), with no ack/error
  convention, no identify and no state query. 2.0 sends one reply line
  per command.
- 1.x always busy-waited 2 s. In 2.0 the settle time can be set, and is
  skipped when the servo is already at the angle.
- 1.x parked the servo at 90° on `LASER 0`. 2.0 leaves it where it is.

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
| travel | 0–100 / 0–120 | 0–40 | software endstops on |
| homing | sensorless | sensorless, stall sensitivity 8 | drives into the hard stop |

Other relevant options:

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

## Source-measure unit

The same **Undalogic miniSMU MS01** that SMUniversal uses (serial
`LUNAR-TUVOK-7966`, firmware 1.4.6). SMUniversal's bench record for it
is in `SMUniversal_Lab_Suite/docs/instruments/undalogic-minismu.md`.

- **Channel 1** measures photocurrent at 0 V bias. Expected signal: low
  µA down to nA, *unverified*.
- **Channel 2** is free. Agreed use: a reference photodiode on a corner
  of the AB stage, outside the sample area.
- **Streaming** (`SOUR<n>:DATA:STREAM`, rate set with
  `SOUR<n>:DATA:SRATE`, packets timestamped by the SMU's own clock) is
  what makes continuous scanning possible. First measured on this
  bench, 2026-10-19; findings below.
- SMUniversal measured **150–180 nA open-circuit current at 0.1 V** on
  this unit.
- Firmware is still **1.4.6**: Undalogic's update server returned HTTP
  500. The library says 1.5.0+ adds the active current range to each
  packet.

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
