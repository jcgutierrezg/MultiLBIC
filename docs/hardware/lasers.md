---
type: reference
title: "Lasers"
---

# Lasers

Six lasers sit fixed on a servo-driven revolver. The servo turns only
180°, so they are mounted as **two groups of three**: lasers 1/4, 2/5
and 3/6 share a servo angle, and XY selects the group by moving the AB
centre under it.

| Laser | Wavelength | Servo | `xy_centre_mm` | Spot, 10–90 % | On the photodiode |
|---|---|---|---|---|---|
| 1 | 444 nm | 150° | 78.965, 72.094 | 68 µm | about −0.77 mA |
| 2 | 519 nm | 90° | 76.058, 72.604 | 42 µm | tens of µA, falling (below) |
| 3 | 652 nm | 30° | 74.854, 70.383 | 35 µm | −1.22 mA |
| 4 | 676 nm | 150° | 48.921, 43.868 | 100 µm | −1.56 mA |
| 5 | 785 nm | 90° | 48.900, 42.213 | 75 µm | −1.30 mA |
| 6 | 848 nm | 30° | 49.501, 38.264 | 73 µm | −2.01 mA |

Positions and spots are from the commissioning of 2026-11-03
(`20261103T175926Z_commission`), across the blade at the sample's
height; powers from the reads after the supply's trimmer that day.
Laser 5's is from 2026-11-10: it had moved 0.89 mm along X since
11-03, enough that the Power tab read the photodiode at its old place
three times before it was found again.
Laser 3 is the **reference laser** (D28): calibrations are made under
it. Laser 2 was until 2026-11-05.

- **Each laser lights alone at its own angle** (checked one at a time,
  2026-10-20). Lasers 5 and 6 are dim or invisible by eye: 5 shows on a
  phone camera, 6 only there or on an IR card.
- **Handling in the box moves lasers** by up to 1 mm (lasers 1–3
  between 2026-10-30 and 11-03, each its own way, while 4–6, not
  touched, held). After any work inside: commission all six
  ([commissioning](../commissioning.md#when)).
- **Power**, on a Thorlabs PM100USB with an S120VC at the sample's
  place (the Power tab, 2026-11-10; `*_powercal_laser<N>.json`):

  | Laser | Meter | Photodiode's response | Against the datasheet |
  |---|---|---|---|
  | 1 | 2.87 mW | 0.2464 A/W | +8 % |
  | 2 | 0.04–0.08 mW | not kept | |
  | 3 | 2.75 mW | 0.4375 A/W | −1 % |
  | 4 | 3.41 mW | 0.4559 A/W | −1 % |
  | 5 | 2.47 mW | 0.5268 A/W | +1 % |
  | 6 | 3.47 mW | 0.5657 A/W | +4 % |

  The photodiode follows its datasheet within 4 % from red to infrared,
  so the beam is all on it. Laser 2 rose 44–77 % between the
  photodiode's two reads in each of three tries (60 s warm-up), so its
  response (0.38–0.50 A/W, up to +58 %) was not kept: it uses the
  datasheet until it is measured again with a long warm-up (600 s), the
  box closed and the room dark. Class *unverified*.

## Laser board firmware

[`MultiLBIC_Laser.ino`](../../firmware/laser/MultiLBIC_Laser/MultiLBIC_Laser.ino),
**2.1.0** on the board since 2026-11-05. Laser enables on pins 1, 2, 3,
4, 5, 8, the servo on pin 9; pins 0, 6, 7 and 10 free. Its protocol is
in [devices](../devices.md#laser-board-protocol-21).

- **Switching is exact**: a switch that turns the servo takes the
  settle time to within 1 ms; a same-angle switch (1↔4, 2↔5, 3↔6) 1 ms.
- **Settle 2000 ms** (D10, `[laser_board] settle_ms`, set at every
  `open()` since the firmware forgets it at power-up). On the worst
  swing, 30° to 150°, 1000 ms was steady and 500 ms let the spot slide.
- **The servo is released after each turn** (`RELEASE 1`,
  `release_servo = true`): the gearbox holds the revolver (below).

## The servo

**It doesn't put a laser back where it was.** Laser 3 held still on a
blade edge moved 0.1 µm; after each of ten servo turns away and back it
landed with a spread of 44 µm along A and 20 µm along B, up to 185 µm
from the first landing (2026-11-04, `servo_position.py`). Every
selection lands a laser somewhere new, within about ±0.1 mm. Hence
**every run locates each laser on the photodiode right after selecting
it** and places its map from there (0.6.43,
[run](../run.md#placing-each-laser-from-the-photodiode)). Located, the
lasers are found 0.1–0.4 mm from `machine.toml`, differently each run.

**Held powered, it moved the beam on its own**: with nothing else
moving, the spot jumped 7–40 µm at random moments for minutes after a
turn, all one way (2026-11-05, `servo_creep.py`, `servo_ab.py`). Its
controller correcting itself, most likely. Released (firmware 2.1.0),
the same tests held within 0.3 µm before any turn and under 2 µm in the
2 minutes after one.

## The laser supply

All six lasers hang on one LM317 with one trimmer, fed from the SKR's
5 V, which also feeds the servo. An LM317 drops about 3 V, which leaves
about 2 V: enough for the red and infrared diodes, not for green
(laser 2) or blue (laser 1), which need 3.5–5 V. Turning the trimmer up
(2026-11-03) took laser 1 up 14 % and laser 2 up 68 %; lasers 3–6, whose
modules hold their own current, moved 1–5 %. It is at its ceiling. The
fix for lasers 1 and 2 is hardware: a supply above 5 V, or a low-dropout
constant-current driver for those two.

What each module needs from the new laser board (a regulator inside or
not, the voltage it needs, light against current) was measured module
by module on the miniSMU, 2026-11-10 and -11
([testing a laser module](../bench.md#testing-a-laser-module); reports
in `bench-results/`). The board that follows from it is proposed in
[laser board](laser-board.md).

| Laser | Inside | A clean diode, current forced | On today's board (3.26 V) |
|---|---|---|---|
| 1 | nothing: a diode and series resistance | lases from 29.3 mA, 0.275 mW/mA, 3.95 mW at 43.5 mA (3.34 V) | 40 mA, ~3 mW; about 10 mW per volt |
| 2 | nothing: a diode and series resistance | lases from 28.4 mA, ~0.13 mW/mA*, ~1.7 mW* at 40.7 mA (3.71 V) | ~26 mA: **below threshold** |
| 3 | a driver | lases from 13.1 mA, 0.347 mW/mA, 3.28 mW at 22.5 mA (2.42 V) | on its driver: 16.4 mA, 2.75 mW |
| 4 | a regulator | lases from 16.5 mA, 0.555 mW/mA, to 22.5 mA (2.45 V) | on its regulator: 3.45 mW |
| 5 | a driver | lases from 8.7 mA, 0.14-0.18 mW/mA†, to 19.5 mA (2.00 V) | on its driver: 16 mA, 2.47 mW |
| 6 | a driver | lases from 6.2 mA, 0.565 mW/mA, 2.98 mW at 11.5 mA (1.87 V) | on its driver: 10 mA, 3.47 mW |

\* from the datasheet response, ±25 %. † laser 5's light read 40 % under
the power meter's: its beam was probably part off the photodiode.

**Every module is a clean diode under a forced current below where its
driver or regulator takes over**, and steady there: held 60 s at a
constant current, lasers 1, 3, 4 and 6 moved 1 % or less. Pushed past
that point a driver switches on (the voltage jumps, the current falls
or the light jumps) and stays on coming down; a regulator turns the
voltage steep.

- **Laser 4** (`20261110T172152Z`): below its regulator the diode and
  about 25 ohm, 1.85 V at 1 mA to 2.45 V at 22 mA. The regulator takes
  over at about 22.5 mA (2.72 V, then 3.55 V at 22.9 mA) and holds
  3.45 mW, what the board gives it. A current held below 22.5 mA dims
  it.
- **Laser 3** (`20261110T174053Z`, `20261110T175436Z`): forced to 23 mA,
  5.5 V and 16.6 mA with 3.16 mW, more than 16.6 mA gives it as a diode;
  coming down it stayed so to 16 mA (4.16 V, 2.89 mW), then fell back
  to the diode (15.5 mA, 0.85 mW). On a plain supply it is a diode to
  2.5 V (22.8 mA, 3.40 mW), then its driver takes over, the current
  falling to 16.0 mA by 3.9 V: **2.75 mW at 16.4 mA at the board's
  3.26 V** (the power meter read 2.75), 3.05 mW at 5 V, about 5 % per
  volt. Held at 3.26 V, +0.1 % in 60 s. At 3.0 V it gives the light of
  about 21 mA through its diode for 16.8 mA drawn: a switching or
  pulsed driver; if pulsed, its peak power is above the mean.
- **Laser 5** (four passes; `20261111T134350Z` the full one): a diode to
  19.5 mA and 2.00 V, its light per mA easing to 77 % of its best from
  18 mA, then its driver: forced past it, 5.5 V and 16.9 mA, staying so
  down to 16 mA. On a plain supply its current peaks at 19.7 mA at
  2.10 V and settles to 16.1 mA by 2.75 V, as on the board (16 mA at
  3.26 V), its light up 8 % from 3.3 to 5.5 V. Its light read 766 uA at
  3.26 V where the Power tab read 1301 on the board at the same current:
  the beam part off the photodiode, which its holds' 6-11 % wobble and
  a slope that changed 23 % between passes agree with. Its shape stands;
  its milliwatts don't.
- **Laser 6** (`20261111T135440Z`): the steepest, 0.565 mW per mA from
  6.2 mA. Forced to 12 mA it switched: 5.54 V, 11.2 mA, and its light
  up 38 % to 4.10 mW. On a plain supply it reached the light ceiling at
  1.93 V (13.4 mA) still a diode, so its driver takes over above that,
  past a light peak above 4 mW. On the board, on its driver, 3.47 mW at
  3.26 V; 4.10 mW at 5.5 V: do not raise its supply.
- **Laser 1** (`20261111T161647Z`): no driver. Its threshold, 29.3 mA, is
  the highest; 3.95 mW at 43.5 mA, where the light ceiling stopped it.
  At 3.26 V it takes 40.4 mA, about 3.0 mW (the board's 42 mA gave
  2.87); 3.25 to 3.34 V takes it from 40 to 43.5 mA and about 3.0 to
  3.95 mW. "Starved" was wrong for it: the board's voltage sets its
  current, and a little more voltage pushes it hard.
- **Laser 2** (`20261111T163449Z`, capped at 60 mA): no driver either.
  It lases from 28.4 mA, and **the board's 3.26 V gives it about
  25.6 mA, just under its threshold**: hence a fortieth of the others'
  light, its swings and its minutes of brightening (near threshold a
  little warming moves the light a lot). At 38.7 mA it held within 4 %
  over 60 s, wobbling 10 %.
- **Lasers 1 and 2 don't settle under a forced voltage**: the miniSMU
  read up to 0.4 V under the voltage set, and at a hold of 3.27 V
  (laser 1) and 3.67 V (laser 2) they did not lase. Into a 100 ohm
  resistor it reached every voltage to 4 V within 2 mV
  ([smu](smu.md)), so it is these modules: pulsed current, or
  oscillating with the instrument's loop. Under a forced current both
  are smooth.

- **Laser 2 is weak and getting weaker.** It gives about a fortieth of
  laser 3's light on the photodiode, and on the cell a few percent of
  the others': the supply holds it just under its lasing threshold
  (above). Readings: −47 µA (2026-10-30), −17.5 and −29 µA after the
  trimmer (11-03), 41 µA (11-05), 26 µA (11-06), and on 11-06 it needed
  the full sweeps to locate. It also swings between runs on the same
  day (−11 to −48 µA, 11-04), so its cable or connector is suspect too.
  It is no longer the reference for this reason.
- **Laser 2 rises for minutes after lighting**: −27.6 µA in the first
  10 s, −38.0 at 1 min, −44.5 at 3 min and still climbing (2026-11-03).
  The 60 s warm-up (D16) leaves it at about 85 % of its 3-minute level,
  so a laser 2 map brightens down its rows.
- **Laser 1 relit too soon comes back at 40 %**, and stays there: dark
  for under 1.5 s before relighting, it read 38–41 µA on the cell; 2 s
  or more, 85–87 µA (2026-10-27). Not the servo (the firmware doesn't
  turn it for a laser already at its angle). The driver keeps a laser
  dark for `relight_ms` (3000) before relighting it, and selecting the
  laser already on sends nothing.
- **Laser 1 drifts** a few percent to 15 % over a run (93 to 80 µA over
  half a minute once).

## Spots and focus

Spots are the 10–90 % width across the blade at the sample's height,
from commissioning; focus assist measures them live while the focus is
turned ([commissioning](../commissioning.md#focus)).

- **Every spot is narrower on the upper blade**, 0.4 mm above the
  sample's plane: the waist sits above the plane, or the spot is
  astigmatic. Focus assist on both edges tells which.
- **Refocusing moves the beam** by up to a few tenths of a mm (laser 2,
  2026-10-26): a refocused laser has a new position, which focus
  assist measures before it saves.

## How well the lasers line up

Each laser is placed from the photodiode, but its beam meets the blades
a little above the cell, at its own angle, so on the cell it lands tens
of µm from where the blades put it, the same way each run. The line-up
([commissioning](../commissioning.md#line-up)) measures that per laser
on a cell's corner, as `cell_offset_xy_mm` against laser 3:

| Laser | First line-up, 2026-11-05: offset saved, µm (X, Y) | Second, 2026-11-06: change proposed |
|---|---|---|
| 1 | −21, −8 | −35, −5 |
| 2 | −8, +63 | +4, +8 |
| 3 | 0, 0 (reference) | 0, 0 |
| 4 | −86, +80 | −13, +24 |
| 5 | −14, +108 | −15, +24 |
| 6 | −20, +59 | −24, +10 |

- Before the offsets, the lasers put the cell's edges 86 µm apart along
  u and 116 µm along v (`20261105T181317Z_lineup_test-lineup`); laser 4
  furthest, as in every map since 2026-11-03.
- With them, 39 µm and 29 µm (`20261106T115355Z_lineup_test-lineup`).
- Run to run, each laser repeats within about 20 µm (three six-laser
  maps, 2026-11-05). Part of the second proposal is laser 3 itself: the
  other five moved against it by about −17, +12 µm together. So the
  first offsets stay, and a better set would average several line-ups.
