---
type: reference
title: "Hardware"
---

# Hardware

What the machine is, as measured on the bench. Values the software uses
live in [`machine.toml`](../multilbic/config/machine.toml); this page and
the ones below say where they come from.

| Page | What it covers |
|---|---|
| [lasers](hardware/lasers.md) | the revolver, each laser's position, spot and power, the servo, the laser supply, how well the lasers line up |
| [motion](hardware/motion.md) | Marlin: its configuration, what MultiLBIC changes at connect, speeds, homing, limits |
| [smu](hardware/smu.md) | the miniSMU: ranges, streaming, noise, the channel-2 offset |
| [photodiode](hardware/photodiode.md) | the reference photodiode on channel 2: the part, its blades, reaching it |
| [timing](hardware/timing.md) | how well a sample's position is known: stamps, row replies, the sync check |

How the software talks to each device is in [devices](devices.md).

## Topology

```
Raspberry Pi 4, Ubuntu 24.04 (monitor attached, runs the window)
 ├── USB  BTT SKR 1.4 Turbo, Marlin 2.1.2.4     motion: X Y (Z) A B
 ├── USB  Seeeduino Xiao "laser board", 2.1.0    servo revolver + 6 laser enables
 ├── USB  Undalogic miniSMU MS01, 1.4.6          ch1 the cell, ch2 the photodiode
 └── USB-TTL  BTT TFT35 touchscreen              wired, unused
```

There are no udev rules. `machine.toml` names each board by the link
Linux builds from its USB serial number under `/dev/serial/by-id/`, so
plug-in order doesn't matter:

| Board | USB id | Serial number |
|---|---|---|
| SKR 1.4 Turbo (Marlin) | `1d50:6029` "Marlin_USB_Device" | `1602400395D510E961DB1B78F50020C1` (line 2 of [`Serials.txt`](../deploy/pi/Serials.txt)) |
| Laser Xiao | `2886:802f` "Seeed_XIAO_M0" | `AC5401405154315432202020FF102436` (line 3) |
| miniSMU | `303a:82a6` "miniSMU_MS01" | `lunar-tuvok-7966` |
| TFT35 adapter | `0403:6001` FTDI TTL232R-3V3 | `FTDKEIR6` |

Line 1 of `Serials.txt` is the retired "instrumentation" Xiao, which
the miniSMU replaced. A replaced board has a new serial, so its path in
`machine.toml` changes: `python -m multilbic.bench.ports --real` shows
it.

## Mechanics

- **The XY stage carries the whole AB gantry**, so both move the sample:
  - **AB** does the raster: 1 mm lead screws, 3200 steps/mm
    (0.3125 µm a microstep), 40 mm between the hard stops.
  - **XY** puts the AB centre under the chosen laser and moves samples
    larger than AB's range: 2 mm lead screws, 400 steps/mm (2.5 µm).
  - The A/B motor couplings sit on a flat ground into each shaft, and
    the rods are greased (2026-11-04).
- **XY and AB move the sample the same ways**: +X as +A, +Y as +B, and
  both home to the same corner (`x_along = "+A"`, `y_along = "+B"`,
  checked 2026-10-21).
- **As the operator stands**, +A and +X move the stage to the right and
  +B and +Y move it up, so the spot runs left and down over the sample.
  A scan starts at the sample's **top-right corner**, rows run leftwards
  (+A) and step downwards (+B); that corner is the calibration corner,
  and `[display]` (`u_points = "left"`, `v_points = "down"`) draws maps
  the same way round. The window's jog arrows move the stage the way
  they point.
- **Z has a driver and no motor.** Marlin would not build XYAB without
  it; the software never moves Z.
- **There is no focus axis.** Each laser is focused by hand at the
  laser, so spot size relies on the sample sitting at the height the
  lasers were focused for ([focus assist](commissioning.md#focus)).

## Samples and their contacts

Samples are solar cells, 100–300 µm thick, typically 10, 20 or 30 mm
square, at 0 V on channel 1. The test cell (`std_test_v2`) is contacted
by silver paint underneath and a crocodile clip on top.

- **A clip can lose contact when the stage moves**, homing especially:
  a check or a map then reads nA where µA is expected, on every laser.
  Reseat the clip, press the cell down, and run it again. The final
  stage solders its contacts, so there is no software check for this.
- **Leads come in from the top, strain-relieved.** A lead tugged by the
  stage's travel gave flat maps and row-to-row jumps.
- **The box is closed for lasers 5 and 6** (near-infrared, invisible)
  and for every map: room light adds µA and 100 Hz flicker, where the
  box leaves nA ([smu](hardware/smu.md#noise)). It is a cardboard box
  for now; nothing interlocks it.

## USB at boot

The miniSMU has its own power switch: switched off, it is simply absent
from USB. Switch it on before starting the software.

The laser Xiao sometimes fails to appear after the Pi boots (seen twice,
2026-10-19 and -20, once after a cold start): the kernel makes no
attempt and logs no error, and a replug brings it back. No
under-voltage was logged, and two later cold starts were fine, so power
order alone doesn't explain it. With its USB unplugged and the laser
supply on, its 3V3 pin reads 0.3 V: a small leak back through the
signal lines.

`deploy/pi/usb-check.sh` runs as a root service at every boot: if the
Xiao hasn't appeared after 15 s, it switches the Pi's USB power off and
on with `uhubctl` (a replug, all ports at once), and logs every boot
(`journalctl -t multilbic-usb-check`). A forced cycle was verified on
2026-10-20 (the Xiao back 7 s later); the failure hasn't recurred since.
If it does often, the hardware fix is 1–10 kΩ in series on the Xiao's
signal lines. Install steps: [`deploy/pi/`](../deploy/pi/README.md).

## TFT35

Wired over USB-TTL, with no role. Its backlight could reach the sample:
cover it during maps. It may become a jog pendant later (Phase 7).
