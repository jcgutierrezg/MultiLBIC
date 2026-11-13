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

Six identical channels, one per laser, each a current sink: a DAC
sets the current, an op-amp holds it through a MOSFET and a sense
resistor, and the ESP32 reads back each channel's current and its
module's voltage. The SKR's 5 V feeds the lasers; the Pi's USB feeds
the ESP32. Every laser is run on current, below the
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
            └── reverse Schottky across the module                 drain ── ÷2 ──► ESP32 ADC (V)
                                                                   MOSFET (logic level)
 DAC ch n ── clamp (shared enable) ── ÷5 ── op-amp (+)             source
                                            op-amp (−) ── sense 10 Ω ┘── GND
                                     sense voltage ──► ESP32 ADC (I)
 5 V rail ── ÷2 ──► ESP32 ADC (rail)        module V = rail − drain
```

- **Full scale 50 mA**: 10 Ω, 0.1 %, so 0.5 V at 50 mA; the DAC's
  2.5 V divided by 5. 16 bits give under 1 µA a step.
- **Headroom**: laser 2 needs 3.71 V at 41 mA, plus 0.41 V on the sense
  resistor and about 0.1 V on the MOSFET: 4.2 V of the SKR's 5 V. The
  most the sink dissipates is about 0.1 W.
- **One enable for all six**: a small MOSFET on each channel clamps its
  set point to zero, all driven by one line, pulled to "off" from the
  analog 3.3 V and cut by the lid interlock in hardware; each sink's
  gate also has a pull-down. Nothing lights at power-up, at a reset,
  with the ESP32 unplugged or unpowered, or with the lid open. Which
  laser is lit is the DAC's business: the others' set points stay at
  zero (the DAC powers up at zero too), and the readback shows it.
- **Ramp**: the firmware moves a set point in steps over about 20 ms,
  from zero at every switch-on, never by a jump.
- **Readback of current and voltage**, every channel, and the rail:
  the sense voltage straight into an ADC input (0-0.5 V, on the ADC's
  smallest range), the drain and the rail each through a ÷2 divider
  (0-2.5 V), so module V = rail − drain. An open cable reads 0 mA and
  the rail's voltage across it; a module whose driver has switched on
  jumps in voltage and stops following its set point; a short reads
  near 0 V; the rail shows the SKR off or sagging. Logged run by run,
  it is the laser health record the plan wants: it would have shown
  laser 2 sitting under its threshold. The ESP32's ADC is good to a few
  percent after its factory calibration: enough for health and faults;
  the light itself is measured by the photodiode.
- **Compensation**: a gate resistor and a small feedback capacitor, and
  a footprint for a capacitor across each module (populated only if a
  scope says so): lasers 1 and 2 did not settle under the miniSMU's
  voltage loop, though they don't pulse on their own
  ([lasers](lasers.md#on-a-scope-2026-11-12)).
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
  on, the enable's pull-up (from the analog 3.3 V) holds every laser
  off.
- One ground point where the SKR's 5 V comes in. WiFi and Bluetooth are
  never used: the firmware never starts them, so their radios add no
  noise and every analog input is free.

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
- **Homed sensorless against a small tab** on the revolver, into a
  rigid hard stop, as A and B home.
- **Driven directly**, no belt: the load is light. With 16 microsteps,
  as A and B, 3200 a turn, 0.11° each, about 80 µm at 40 mm from the
  axis. 60° is no whole number of steps, nor need it be: each laser's
  angle is measured and kept, as the servo's are now.
- **Marlin's Z as an angle**: 8.89 steps per degree (3200 / 360),
  travel from the tab to just short of a full turn; held energised.
- **The cables must not wind**: the travel stops short of a turn, with a
  slack loop, no slip ring (contacts in series with a laser's current
  add noise).

**Precision is not the point**: every run still locates each laser on
the photodiode (D29), so the stepper only has to land each beam where
the locate finds it. What it adds is the full turn, all six lasers at
one spot, and no creep.

### The mount (decided 2026-11-12)

- **A ring, as now**: the six lasers' beams parallel to the axis, each
  turned into one working position. Six at 60° instead of two groups
  of three at 180°, so every laser is one XY position and the 30 mm XY
  offset between today's groups goes.
- **Radius about 40 mm**, as now; a little smaller only if the clamps
  still fit. An angle error moves the spot by radius × angle, which the
  locate absorbs.
- **In wavelength order**, lasers 1 to 6 at 60° steps, so a spectral
  sweep turns one way a step at a time. The tab and its stop sit in the
  60° gap between laser 6 and laser 1.
- **Split clamps**, one per laser, in fixed bores at one common height,
  so all six focus at the sample's plane and handling no longer moves
  them (it has by up to 1 mm). No tilt adjusters: the line-up takes the
  small offsets that remain. The focus rings stay reachable.
- **3D printed, directly on the NEMA 17's 5 mm D-shaft** with a
  clamping hub; the motor above, the revolver below.
- **The lasers' leads in a slack loop** over the 300° of travel.
- **The working position** puts the photodiode and the whole sample
  area within XY's reach, and the five lasers not in use clear the
  blades, the clips and the photodiode's post as the ring turns.
- **Held energised or released after each move**: decided once it is
  built, by a map with the motor held against one with it released (if
  the detent holds the revolver). Interference with the miniSMU is not
  expected.

## A temperature stage: later, and not on this board

A heating and cooling stage under the sample (a Peltier, a CPU AIO on
its hot side, a type T surface thermocouple) is for later, and **needs
nothing on the laser board**. The SKR 1.4 Turbo has its heater outputs
(HB, HE0, HE1), fan outputs and thermistor inputs free, since Marlin
runs no extruders, and Marlin already closes temperature loops with
thermal protection. Notes for when it is designed:

- The SKR's inputs read thermistors and RTDs, not thermocouples. Marlin
  reads a thermocouple through a MAX31855 on SPI (it comes in a type T
  version), for the hotends and the bed loop; it has no MCP9600 driver
  and its cooler loop takes analog sensors only (checked 2026-11-12,
  release 2.1.2.9 and bugfix-2.1.x).
- Marlin's `PELTIER_BED` (a relay reversing the Peltier on the bed
  loop) is only in bugfix-2.1.x.

## Other features

| Feature | Why |
|---|---|
| **Box-lid interlock input** (with a jumper to bypass) | lasers 5 and 6 are invisible; an open box cuts the enable in hardware |
| **A "laser on" output** for a lamp outside the box | you see a laser is lit without opening the box; the board itself, in the box, shows no light |
| **Lasers off when the Pi goes away** (USB disconnect, or no command for a set time while lit) | a crashed program doesn't leave a laser on for hours; the ESP32 is powered by the Pi, so a Pi shut down takes it too |
| **Readback of each laser's current and voltage, and the rail**, logged with every run | laser health, open cables, shorts, a driver switching on, the SKR off |
| **A thermocouple** near the lasers, through an MCP9600 module on the DAC's I²C bus | lasers 1 and 2 drift; the run file can carry the temperature |
| **The enable on a PWM-capable pin** | chopping the lit laser to separate slow drift (D8) stays possible later, with no hardware change |
| **A spare line to the SKR** | the hardware row marker (D33, dropped) or a trigger, should either come back |
| **A switched auxiliary output** (5 V) | a box light or fan, off during maps |
| **Test points** on every sense resistor, drain and the rail | bring-up and repairs with a multimeter |
| **Keyed, labelled connectors**, 3-pin where 5 V is on them | a module can't go on backwards, nor take 5 V from the lamp or aux socket |
| **`ID?` with the board's revision and serial** | the driver knows which board it has |

Left out on purpose: the temperature stage (the SKR's, above),
a buzzer for "run finished" and errors (a 12 V one on the SKR's fan
output, [plan](../plan.md#later)),
spare channels, a display (the Pi has one),
on-board storage of the set points (`machine.toml` is the one place
they live), and WiFi or Bluetooth: USB to the Pi is the only link.

## The ESP32's pins

The ESP32-S3 has no DAC, and 20 analog inputs on GPIO1-20 (ADC1 on
1-10, ADC2 on 11-20; ADC2 would clash only with WiFi, never on). Kept
clear of:

- **the strapping pins, GPIO0, 3, 45 and 46**, read at reset to choose
  the boot mode, the JTAG source and the flash voltage: a laser board
  pulling one the wrong way can stop the ESP32 booting;
- **GPIO19 and 20**, its native USB to the Pi;
- **GPIO43 and 44**, UART0, wired to the dev board's USB-serial chip and
  the boot messages;
- **GPIO35, 36 and 37**, taken by the PSRAM on modules that have octal
  PSRAM (the N8R8 and N16R8 kinds);
- **GPIO38 and 48**, the dev board's RGB LED (one or the other, by its
  revision);
- **GPIO47** as well, since on modules whose flash runs at 1.8 V it
  does too.

That leaves 22 safe pins: GPIO1, 2, 4-18, 21 and 39-42 (39-42 are the
JTAG pins, plain GPIO while JTAG goes over USB, the default).

| Pin | Use | Notes |
|---|---|---|
| GPIO1, 2, 4, 5, 6, 7 | current, lasers 1-6 | ADC1; the sense voltage, 0-0.5 V |
| GPIO10, 11, 12, 13, 14, 15 | drain, lasers 1-6 | ADC1 and ADC2; ÷2 |
| GPIO17 | the 5 V rail | ADC2; ÷2 |
| GPIO8, 9 | I²C: the DAC and the MCP9600 (SDA, SCL) | the Arduino defaults on the S3; each part on its own address |
| GPIO21 | the shared enable, high = enabled | PWM-capable; through a MOSFET, so "off" with the ESP32 unpowered or in reset |
| GPIO39 | lid interlock in | also cuts the enable in hardware |
| GPIO40 | "laser on" lamp out | through a transistor |
| GPIO42 | auxiliary output | through a MOSFET |
| GPIO16 | spare line to the SKR | through a resistor |
| GPIO18, 41 | spare | 18 analog-capable |

20 of the 22 safe pins used. Every line into the board goes through
1-10 kΩ (back-feeding, above).

## Bill of materials (draft)

The [schematic](laser-board-schematic.md) gives the nets, designators
and pin numbers, and a layout guide; this list follows it.

Hand-solderable parts (SOIC, TSSOP, SOT-23, 0805), each stocked at RS
or Farnell and also at LCSC, so the board can be assembled by hand or
by a PCB house. Part numbers are to be checked for stock before
ordering; an equivalent is fine where the notes say what matters.

### Per channel (× 6)

| Part | Value / part | Qty | What matters |
|---|---|---|---|
| Sink MOSFET | Nexperia PMV30UN2 (or AO3400A), SOT-23 | 6 | fully on at 2.5 V gate (the op-amps run on 3.3 V), a few hundred pF; 0.25 W into a shorted module is within its rating |
| Sense resistor | 10 Ω, 0.1 %, 25 ppm/K, 0805 thin film (Vishay TNPW0805) | 6 | sets the current: 0.5 V at 50 mA |
| Set-point divider | 40.2 kΩ and 10 kΩ, 0.1 %, 0805 | 6 + 6 | ÷5, the DAC's 2.5 V to 0.5 V; its exact ratio is calibrated out |
| Clamp MOSFET | BSS138, SOT-23 | 6 | across the 10 kΩ, on the shared enable; on below 1.5 V |
| Set-point capacitor | 10 nF C0G, 0805 | 6 | after the divider: filters the DAC's noise at the amplifier's input |
| Loop parts | gate 220 Ω, feedback 1 kΩ, 10 nF C0G, gate pull-down 100 kΩ | 6 each | stability with the MOSFET's capacitance |
| Module capacitor | 100 nF, 0805 | 6 footprints | **not fitted** unless a scope on the prototype asks for it |
| Reverse diode | BAT54, SOT-23 | 6 | across each module |
| Drain divider | 1 MΩ + 1 MΩ, 0.1 %, 0805 | 12 | see the note below the tables |
| Readback filter | 10 kΩ in series on the current readback; 100 nF at each ADC pin | 6 + 12 | the drain readback's 1 MΩ is its series resistor |
| Laser connector | JST B2B-XH-A (2-pin) + XHP-2 housing + SXH-001T-P0.6 crimps | 6 | keyed |

### Shared

| Part | Value / part | Qty | What matters |
|---|---|---|---|
| Microcontroller | Espressif ESP32-S3-DevKitC-1-N8R8, on 2 × 22-pin female headers | 1 | native USB to the Pi; its 5 V and 3V3 pins left unconnected |
| DAC | Analog Devices AD5675RBRUZ, TSSOP-20 | 1 | 8 × 16 bit, I²C, 2.5 V internal reference, powers up at zero; two outputs spare |
| Op-amps | Microchip MCP6V34-E/SL, SOIC-14 | 2 | quad, zero drift, rail to rail, 3.3 V; the two spare amplifiers tied off as followers at half the supply (2 × 100 kΩ) |
| Analog 3.3 V | TI LP5907MFX-3.3, SOT-23-5, with 1 µF in and out | 1 | low noise, from the SKR's 5 V |
| Supply input | Bourns MF-MSMF030-2 polyfuse (0.3 A hold, 1812); 330 µF 10 V low-ESR electrolytic; 10 µF ceramic | 1 each | the SKR's 5 V in |
| Rail readback | 1 MΩ + 1 MΩ, 0.1 %; 100 nF | 1 set | |
| Decoupling | 100 nF per IC, 10 µF on the 3.3 V and at the DAC | ~8 | |
| I²C | 4.7 kΩ pull-ups to the analog 3.3 V, 330 Ω in series from the ESP32 | 2 + 2 | small series resistors, so the low level stays low |
| Enable | 10 kΩ pull-up to the analog 3.3 V ("off"); a BSS138 pulls it low through the lid switch, its gate from GPIO21 through 1 kΩ, with 100 kΩ to ground; 100 kΩ pull-up on the lid line | 1 set | the ESP32 unpowered cannot hold the line half-way ([schematic](laser-board-schematic.md)) |
| Other ESP32 lines | 1 kΩ in series (lid, lamp, aux, SKR line) | 4 | no back-feeding with the SKR off |
| Lamp and aux outputs | AO3400A low side, 100 kΩ gate pull-down, SS14 flyback footprint | 2 | switch the board's 5 V after the polyfuse, about 0.2 A together |
| Temperature | Adafruit MCP9600 breakout (4101) or Pimoroni PIM437, on a female header; type K thermocouple | 1 | I²C at 0x67; the DAC at 0x0C-0x0F |
| Connectors | JST B3B-XH-A 3-pin, the middle pin unused: 5 V in, lamp, aux. JST B2B-XH-A 2-pin: lid, SKR line. Housings and crimps | 3 + 2 | a laser's 2-pin plug in a 5 V socket meets one live pin at most |
| Test points | loops or pads on each sense resistor, drain, the rail, the 3.3 V, GND | ~16 | |
| PCB | 2 layers, 1.6 mm, ground pour, about 100 × 80 mm | 1 | |

### Off the board

| Part | Qty | Notes |
|---|---|---|
| NEMA 17, the same model as A and B | 1 | one spare then fits all three; on the SKR's Z socket |
| Lid switch: a microswitch (Omron SS-5 class) or a reed and magnet | 1 | closed with the lid shut |
| Laser-on lamp, 5 V | 1 | outside the box |
| 100 Ω dummy load, 0.1 % | 1 | calibration and bring-up |
| Buzzer, 12 V: PUI Audio AI-3135-TF-LW100-R, with a JST XHP-2 housing and crimps | 1 | not this board's: on the SKR's FAN0 socket, for "run finished" and errors ([plan](../plan.md#later)). A piezo with its own drive circuit, 3-20 V, 15 mA at most, flange mount, on leads. Polarised: its + lead to the socket's + (colours from its datasheet). Loud (105 dB as rated); tape over its opening quietens it |

### Notes

- **1 MΩ drain dividers, not 100 kΩ**: a drain divider is a path from
  the rail through the module even with its sink off. With 100 kΩ
  that is 25 µA through every unlit laser, enough for a faint glow
  near a cell read in nA; with 1 MΩ it is 2.5 µA. The 100 nF at the ADC
  pin keeps the high impedance from bothering the ADC, at a few
  milliseconds of settling, nothing for a health readback.
- **No light from the board**: it sits inside the box, with the cell
  read in nA, so it carries no LEDs, and the lamp outside says a laser
  is lit. The dev board's power LED is always on: removed, or covered
  with black tape, and likewise any power LED on the MCP9600 breakout.
  The dev board's RGB LED stays off, as the firmware never drives it.
- **The aux output switches 5 V only**: the board has no 12 V. A 12 V
  fan or light would take its own supply, switched by the aux output's
  MOSFET. Lamp and aux share the polyfuse with the lasers, so about
  0.2 A between them; a 5 V fan wants the 0.5 A polyfuse.

## Firmware and software

- **Firmware 3.0** on the ESP32 (Arduino, as today), same line protocol:
  `LASER <n>` lights laser n at its set point (ramped), `LASER 0`/`OFF`,
  `SET <n> <mA>`, `MAX <n> <mA>`, `READ <n>` (its current and its
  module's voltage), `RAIL?`, `LID?`, `STATE?`, `ID?`, `TEMP?`; the
  servo commands go. The firmware lights one laser at a time and turns
  everything off on a fault the readback shows.
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
- Laser 2: its power with the power meter (calibrated on the board, not
  the datasheet), and whether 1.7 mW is enough or it is replaced.
- Laser 5's light, measured again with its beam centred on the
  photodiode.
- Lasers 1 and 2 on a prototype channel, on a scope (do they settle
  under the board's current loop?). The modules don't pulse (all steady
  on a scope, 2026-11-12); it was the miniSMU's voltage loop that
  oscillated with them.

## Bring-up

1. One channel on a breadboard or the first board: the 100 Ω dummy and
   the miniSMU, set point against current, its calibration.
2. Each module on its channel, swept as `laser_module` sweeps it, the
   photodiode reading, to confirm the table above and each `max_ma`.
3. The power meter on each laser at its set point (the Power tab).
4. The revolver: it homes, each laser lands where the locate finds
   it, and a map with the motor held against one with it released.
5. Commission all six, then a six-laser map against one from the old
   board.
