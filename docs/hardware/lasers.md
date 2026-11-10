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
not, the voltage it needs, light against current) is measured module by
module on the miniSMU ([testing a laser module](../bench.md#testing-a-laser-module)).

- **Laser 4** (2026-11-10, `20261110T172152Z_laser_module_real`): lases
  from 16.5 mA at 0.555 mW per mA, straight, up and down within 0.4 %.
  Below its regulator it is the diode and about 25 ohm: 1.85 V at 1 mA,
  2.45 V at 22 mA. Its own regulator takes over at about 22.5 mA
  (2.72 V, then 3.55 V at 22.9 mA) and holds 3.45 mW, what the board
  gives it today at 3.26 V (23 mA). So it sets its own power from about
  2.7 V up, and a current held below 22.5 mA dims it. Held 60 s at
  21.5 mA, the light moved under 1 % at constant voltage or current.
- **Laser 3** (2026-11-10, `20261110T174053Z_laser_module_real`): a
  plain diode up to 22.5 mA (2.42 V, about 16 ohm), lasing from 13.1 mA
  at 0.347 mW per mA, to 3.28 mW. Forced to 23 mA, the voltage jumped to
  5.5 V and the current fell to 16.6 mA while the light held 3.16 mW,
  more than 16.6 mA gives it as a diode: a driver inside, switching
  most likely. Coming down it stayed so until 16 mA (4.16 V, 2.89 mW),
  then fell back to the diode (15.5 mA, 2.29 V, 0.85 mW). On the board
  it runs on that driver: 16 mA at 3.26 V, 2.75 mW. At 16 mA it has two
  states, 0.9 mW at 2.3 V or 2.9 mW at 4.2 V, so it wants a fixed
  voltage, not a current.

  On a plain supply (`20261110T175436Z_laser_module_real`) it is smooth:
  a diode to 2.5 V, where its current peaks at 22.8 mA and its light at
  3.40 mW; then its driver takes over, the current falling to 16.0 mA by
  3.9 V while the light settles. 2.72 mW at 3.0 V, **2.75 mW at 16.4 mA
  at the board's 3.26 V** (the power meter read 2.75), 2.87 mW at 4 V,
  3.05 mW at 5 V, 3.13 mW at 5.5 V: about 5 % per volt around 3.3 V.
  Held 60 s at 3.26 V the light moved +0.1 %. At 3.0 V it gives the light
  of about 21 mA through its diode while drawing 16.8 mA, which a
  switching converter or a pulsed drive explains; if pulsed, its peak
  power is above the mean the photodiode reads (a scope on the
  photodiode would tell).
- **Laser 5** (2026-11-10, `20261110T180425Z_laser_module_real`, a first
  pass): a diode lasing from 8.7 mA at 0.18 mW per mA, to 0.86 mW at
  13.5 mA (1.88 V), where a dip in its light stopped the test as a bend.
  On the board it draws 16 mA for 2.47 mW, twice what that diode curve
  gives at 16 mA: a driver, as laser 3's, above where the test stopped.
  Held 60 s its light dipped up to 6 % at random (mode hops, most
  likely). A second pass (`20261110T181543Z`) read three dips again and
  went on to 16 mA (1.16 mW), its light per mA easing from 87 to 74 uA;
  its voltage sweep then stopped when 18.76 mA passed a 15.5 mA limit
  the miniSMU had dropped (hardware/smu.md), about 1.6 mW, harmless.

- **Laser 2 is weak and getting weaker.** It gives about a fortieth of
  laser 3's light on the photodiode, and on the cell a few percent of
  the others'. Readings: −47 µA (2026-10-30), −17.5 and −29 µA after the
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
