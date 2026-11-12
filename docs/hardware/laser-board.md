---
type: reference
title: "Laser board (proposal)"
---

# Laser board (proposal)

**A proposal for review (2026-11-11), nothing built.** It replaces the
Xiao laser board and its one LM317. It follows from the module tests of
2026-11-10 and -11 ([lasers](lasers.md#the-laser-supply)) and from four
choices:

- each laser's power set on its own, from the software;
- an ESP32-class microcontroller, with pins to spare;
- straightforward to use and maintain, over clever to design;
- steady light (no chopping), the lasers powered from the SKR.

## In one paragraph

Eight identical channels, one per laser plus two spare, each a
current sink: a DAC sets the current, an op-amp holds it through a
MOSFET and a sense resistor, and the ESP32 reads back each channel's
current and its module's voltage. The SKR's 5 V feeds the lasers; the
Pi's USB feeds the ESP32. Every laser is run on current, below the
point where its own driver or regulator would take over, so its power
is whatever current the software asks for. The servo goes: the
revolver turns on a NEMA 17 from the SKR's spare Z driver, homed
against a tab, so the board only does lasers.

## Why current, for every laser

Under a forced current, every module tested is a clean diode up to the
point where its driver or regulator takes over, and steady there. Past
that point a driver switches on and stays on, which a voltage supply
turns into two possible states. Ramped from zero to a set point below
that point, a module's driver never switches on:

| Laser | Lases from | Set point range | Most tested | Light there |
|---|---|---|---|---|
| 1 | 29.3 mA | 29-44 mA | 43.5 mA | 3.95 mW |
| 2 | 28.4 mA | 29-41 mA | 40.7 mA | ~1.7 mW (datasheet) |
| 3 | 13.1 mA | 13-21 mA | 22.5 mA, then its driver | 3.28 mW |
| 4 | 16.5 mA | 17-22 mA | 22.5 mA, then its regulator | 3.45 mW |
| 5 | 8.7 mA | 9-18.5 mA | 19.5 mA, then its driver | ~1.6 mW as read |
| 6 | 6.2 mA | 6-11 mA | 11.5 mA, then its driver | 2.98 mW |

The top of each range stays 1 mA under the tested switch point, and is
a hard limit in `machine.toml` and in the firmware. A laser can still
run on its own driver (as today, with no adjustment): set its channel
well above its switch point, the sink stays fully on, and the module
sees the rail. That is a per-laser choice in `machine.toml`.

A common power for all six, for normalising, is about 1.5 mW at most
while laser 2 tops out near 1.7 mW (to be confirmed with the power
meter). Equal photon flux instead of equal power is still open
([plan](../plan.md#later)).

## A channel

```
 5 V rail ──┬── keyed 2-pin connector (+) ── laser module ── (−) ──┐
            │                                                      │
            └── reverse Schottky across the module                 drain
                                                                   MOSFET (logic level)
 DAC ch n ── enable switch ── ÷5 ── op-amp (+)                     source
                                    op-amp (−) ── sense 10 Ω ──────┘── GND
 ESP32 ADC ◄── sense voltage (current)   ESP32 ADC ◄── drain voltage (module V = rail − drain)
```

- **Full scale 50 mA**: 10 Ω, 0.1 %, so 0.5 V at 50 mA; the DAC's
  2.5 V divided by 5. 16 bits give under 1 µA a step.
- **Headroom**: laser 2 needs 3.71 V at 41 mA, plus 0.41 V on the sense
  resistor and about 0.1 V on the MOSFET: 4.2 V of the SKR's 5 V. The
  most the sink dissipates is about 0.1 W.
- **The enable** holds the set point at zero unless the ESP32 drives it
  (a pull-up from the analog 3.3 V), and each MOSFET's gate has a
  pull-down: nothing lights at power-up, at a reset, with the ESP32
  unplugged or unpowered.
- **Ramp**: the firmware moves a set point in steps over about 20 ms,
  from zero at every switch-on, never by a jump.
- **Readback** tells a working channel from an open cable (the sink
  can't reach its current), a module whose driver has switched on (its
  voltage jumps), or a shorted one. Logged run by run, it is the laser
  health record the plan wants, and would have pointed at laser 2's
  supply weeks ago.
- **Compensation**: a gate resistor and a small feedback capacitor, and
  a footprint for a capacitor across each module (populated only if a
  scope says so): lasers 1 and 2 did not settle under the miniSMU's
  voltage loop.
- **Calibration**: each channel once, two points on the 100 Ω dummy
  against the miniSMU, kept in `machine.toml`.

## Supplies

Two supplies, kept apart:

- **The lasers: the SKR's 5 V** (from its 12 V input), as today, with a
  bulk capacitor at the board's input and a polyfuse. Today's trouble
  was never that rail but the LM317's 3 V drop; a sink needs about
  0.5 V. One laser is lit at a time, 50 mA at most. The sinks hold
  their current whatever the rail does above the 4.2 V they need, so
  its ripple barely reaches a laser. A laser left on its own driver
  (the sink fully on) does see the rail: about 5 V instead of today's
  3.26 V, so a little more light (laser 3 about 3.05 mW, laser 6 about
  4 mW).
- **The ESP32: the Pi's USB**, so the Pi's 5 V and the SKR's never meet
  (the ESP32 board's 5 V pin stays off this board).
- **The analog side** (DAC, op-amps, enables) on its own 3.3 V LDO from
  the SKR's 5 V. With the SKR off and the Pi on, the ESP32 runs and the
  sinks have no supply: every line from the ESP32 goes through 1-10 kΩ,
  so nothing back-feeds (the Xiao's 3V3 pin reads 0.3 V that way today,
  [hardware](../hardware.md#usb-at-boot)). With the Pi off and the SKR
  on, the enables' pull-ups (from the analog 3.3 V) hold every laser
  off.
- One ground point where the SKR's 5 V comes in; WiFi and Bluetooth
  off in the firmware.

If a map ever shows the board: a USB isolator between the ESP32 and the
Pi breaks a ground loop with the miniSMU.

## The revolver

Today's servo turns 180° (so the lasers are two groups of three, and XY
picks the group), lands each selection up to 0.185 mm from the last
(every run locates each laser on the photodiode because of it, D29),
and crept while powered. **It goes, for a NEMA 17 like A's and B's**:

- **Driven by the SKR's Z socket**, which has a TMC2209 and no motor
  today. Marlin homes and moves it as it does A and B, and the software
  already speaks Marlin; the laser board loses its servo pin and the
  2 s settle.
- **Homed sensorless against a small tab** on the revolver, into a hard
  stop, as A and B home. The tab costs a few degrees of the turn: the
  six lasers sit 60° apart within the rest, **all aimed at roughly one
  spot**, so every laser is one XY position (a new mount).
- **Driven directly**, no belt: the load is light. With 16 microsteps,
  as A and B, 3200 a turn, 0.11° each, about 60 µm at 30 mm from the
  axis. 60° is no whole number of steps, nor need it be: each laser's
  angle is measured and kept, as the servo's are now, and a stepper
  comes back to the same microstep. The TMC2209 goes to 256 microsteps
  if the bench wants finer.
- **Marlin's Z as an angle**: 8.89 steps per degree (3200 / 360),
  travel from the tab to just short of a full turn; held energised.
- **The cables must not wind**: the travel stops short of a turn, with a
  slack loop, no slip ring (contacts in series with a laser's current
  add noise).

Whether the stepper lands each laser well enough to stop locating it on
the photodiode at every run (D29) is for the bench: ten selections
away and back on a blade edge, as the servo was tested.

## Other features

| Feature | Why |
|---|---|
| **Box-lid interlock input** (with a jumper to bypass) | lasers 5 and 6 are invisible; an open box cuts every enable in hardware |
| **A "laser on" output** for a lamp outside the box, and an LED per channel | you see what is lit without opening the box |
| **Lasers off when the Pi goes away** (USB disconnect, or no command for a set time while lit) | a crashed program doesn't leave a laser on for hours; the ESP32 is powered by the Pi, so a Pi shut down takes it too |
| **Readback of current and voltage**, logged with every run | laser health, open cables, a driver switching on |
| **A temperature sensor** near the lasers (one-wire) | lasers 1 and 2 drift; the run file can carry the temperature |
| **Two spare channels** | a seventh or eighth wavelength without a new board |
| **Enables on PWM-capable pins** | chopping the lasers to separate slow drift (D8) stays possible later, with no hardware change |
| **A spare line to the SKR** | the hardware row marker (D33, dropped) or a trigger, should either come back |
| **A switched auxiliary output** (12 or 5 V) | a box light or fan, off during maps |
| **Test points** on every sense resistor and drain | bring-up and repairs with a multimeter |
| **Keyed, labelled connectors** | a module can't go on backwards |
| **`ID?` with the board's revision and serial** | the driver knows which board it has |

Left out on purpose: a display (the Pi has one), on-board storage of
the set points (`machine.toml` is the one place they live), and WiFi.

## Parts (indicative)

| Part | Suggestion | Notes |
|---|---|---|
| Microcontroller | ESP32-S3 dev board with native USB, on headers | replaceable whole; plenty of ADC pins; appears under `/dev/serial/by-id/` like the Xiao |
| DAC | 8 channels, 16 bit, I²C, internal reference (e.g. AD5675R) | one part for all channels |
| Op-amps | 2 quad, rail-to-rail, zero-drift (e.g. MCP6V34) | low offset: 10 µV is 1 µA on 10 Ω |
| MOSFETs | logic-level N-channel, SOT-23 | 8, plus 8 small ones for the enables |
| Sense resistors | 10 Ω, 0.1 %, low drift | 8 |
| Reverse diodes | small Schottky across each module | 8 |
| Laser supply | the SKR's 5 V: a bulk capacitor (100-470 µF) and a polyfuse at the input | 50 mA at most, one laser lit at a time |
| Analog 3.3 V | low-noise LDO from the SKR's 5 V | |
| Series resistors | 1-10 kΩ on every ESP32 line into the board | no back-feeding with the SKR off |
| Connectors | JST-XH (or Micro-Fit) 2-pin per laser, keyed | |
| Revolver | NEMA 17 (as A and B), direct, a tab for homing, on the SKR's Z driver | Marlin's Z set as degrees, 16 microsteps |

Part numbers are examples to check for stock and footprints, not
choices.

## Firmware and software

- **Firmware 3.0** on the ESP32 (Arduino, as today), same line protocol:
  `LASER <n>` lights laser n at its set point (ramped), `LASER 0`/`OFF`,
  `SET <n> <mA>`, `MAX <n> <mA>`, `READ <n>` (current and voltage),
  `STATE?`, `ID?`, `TEMP?`; the servo commands go.
- **Marlin**: Z as the revolver, in degrees, homed sensorless into the
  tab; selecting a laser becomes `G1 Z<angle>` on the SKR, then
  `LASER <n>` on the board. Each laser's angle goes in `machine.toml`
  instead of its servo angle.
- **The driver** sends each laser's set point and limit from
  `machine.toml` at every `open()`, as it sends the settle time now;
  the firmware refuses anything above a limit.
- **`machine.toml`**: per laser `drive = "current"` or `"own driver"`,
  `set_ma`, `max_ma`; per channel its calibration.
- **The Maintenance window's Power tab** gains "set power": it steps a
  laser's current until the photodiode reads the power wanted, and saves
  the current. Run again as the lasers age.
- **The simulator** gets a fake board with these channels and the
  modules' measured curves (`sim/laser_module.py` has them).
- **A bench probe** to calibrate a channel on the dummy and to sweep a
  module on its channel, as `laser_module` does on the miniSMU.

## Open

- Equal power or equal photon flux.
- The revolver's mount: the lasers 60° apart aimed at one spot, the
  tab, the cables' slack loop.
- Laser 2: its power with the power meter (calibrated on the board, not
  the datasheet), and whether 1.7 mW is enough or it is replaced.
- Laser 5's light, measured again with its beam centred on the
  photodiode.
- A scope on laser 3's photodiode (switching or pulsed driver?) and on
  lasers 1 and 2's supply on a prototype channel (do they settle under
  a current sink?).

## Bring-up

1. One channel on a breadboard or the first board: the 100 Ω dummy and
   the miniSMU, set point against current, its calibration.
2. Each module on its channel, swept as `laser_module` sweeps it, the
   photodiode reading, to confirm the table above and each `max_ma`.
3. The power meter on each laser at its set point (the Power tab).
4. The revolver: homing repeatability, then ten selections of a laser
   away and back on a blade edge.
5. Commission all six, then a six-laser map against one from the old
   board.
