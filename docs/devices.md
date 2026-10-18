---
type: reference
title: "Devices"
---

# Devices

The device layer (`multilbic/hardware/`) and the simulators that stand
in for it (`multilbic/sim/`). What the machine *is* lives in
[hardware](hardware.md). This page is about how the software talks to it.

| Device | Driver | Simulator | Transport |
|---|---|---|---|
| Marlin (SKR 1.4 Turbo) | `hardware/marlin.py` | `sim/fake_marlin.py` | lines over serial (`hardware/link.py`) |
| Laser board (Xiao) | `hardware/laser.py` | `sim/fake_laser.py` | lines over serial |
| miniSMU | `hardware/smu.py` (+ SMUniversal's driver) | `sim/fake_smu.py` | the vendor library, `minismu_py` |

Every driver takes a `Clock` (`multilbic/clock.py`). On the machine that
is real time. In tests it is a `ScaledClock` running 100× faster, so a
15 s row takes 0.15 s and every timeout, sleep and timestamp still
agrees.

The simulators run the **real drivers** over the **same text**. Only
the far end of the cable is fake (`sim/link.py`), so protocol parsing is
tested exactly as it runs on the machine.

## Marlin

The client sends each command with a line number and checksum
(`N12 G1 A5.0000 F60.000*87`). A reader thread sorts everything that comes
back:

| Line from Marlin | What the client does |
|---|---|
| `ok N12 P15 B3` | completes command 12; P/B are planner and buffer space |
| `echo:busy: processing` | restarts the waiting command's silence timer |
| `Error:...Last Line: n` / `Resend: n` / `ok` | resends from line n; the bare `ok` is absorbed |
| `echo:Unknown command: "..."` | the waiting command raises `MarlinCommandError` |
| `Error:Printer halted. kill() called!` | every command raises `MarlinHalted` from then on |
| `start` | the board restarted: pending commands fail, position untrusted |
| `X:... Y:... Count ...` | the answer to `M114`, or stored as an unsolicited report |

Behaviours worth knowing, all checked in the Marlin 2.1.2.4 source:

- **`M114` reports the last *commanded* position**, not a live one.
  During a move it returns the destination. Only after `wait_idle()`
  (`M400`) is it where the stage actually is.
- **Timeouts are silence, not duration.** Marlin sends `busy:` every 2 s
  during `G28` and `M400`, so a 15 s row with a 3 s timeout is fine.
- **Stop is `quickstop()`**: `M410`, written without waiting for
  anything. The emergency parser acts on it as the bytes arrive. The
  line is still queued, and its later `ok` is expected. Afterwards
  Marlin's position is where the steppers actually stopped.
- **Limits are enforced by the client.** Marlin would silently slow a
  too-fast move (the old `F360` ran at 2 mm/s) and silently clamp an
  out-of-range target. The client raises `MotionLimitError` instead.
  The feed limit is checked per axis, the way Marlin scales a move.
- **Absolute moves need a trusted position.** After `home()` it is
  trusted. After `motors(False)` it is not, because the stage may have
  been pushed by hand and Marlin cannot see that. `jog()` stays allowed
  for alignment.
- **A wrong port fails at `open()`**: `M115` must report
  `MACHINE_TYPE:MultiLBIC`.

## Laser board: protocol 2.0

Firmware: [`firmware/laser/MultiLBIC_Laser/MultiLBIC_Laser.ino`](../firmware/laser/MultiLBIC_Laser/MultiLBIC_Laser.ino).
115200 baud, one command per line, **exactly one reply line per
command**.

| Command | Reply | Notes |
|---|---|---|
| `ID?` | `MultiLBIC-Laser,2.0.0` | checked at `open()` |
| `STATE?` | `STATE <laser> <angle>` | laser 0 = all off |
| `ANGLES?` | `ANGLES 150 90 30 150 90 30` | checked against `machine.toml` at `open()` |
| `SETTLE?` | `SETTLE <ms>` | |
| `SETTLE <ms>` | `OK SETTLE <ms>` | 0–10000 |
| `LASER <1-6>` | `OK LASER <n>` | all off, servo turns, waits the settle time, laser on |
| `LASER 0` or `OFF` | `OK OFF` | servo stays where it is |
| anything else | `ERR UNKNOWN` | also `ERR BAD_LASER`, `ERR BAD_VALUE` |

The settle wait is skipped when the servo is already at the angle, so
going from laser 1 to 4 (both 150°) is immediate. After a timeout the
driver refuses commands until `resync()`, because a late reply would
otherwise be read as the answer to the next command.

**Firmware 2.0.0 has not been compiled or flashed yet.** The 1.x sketch
on the board answers in free text, and the driver refuses it at
`open()`.

## miniSMU

Two layers over one `minismu_py.SMU` object:

- **Setup** through SMUniversal's `UndalogicMiniSMU`: identify, reset,
  voltage source, bias, current limit, oversampling, output on/off.
  One driver per channel.
- **Streaming** straight through the library (`SmuStream`). Each sample
  keeps the instrument's own timestamp (`device_ms`) *and* the host's
  receipt time (`host_s`). Mapping one clock onto the other is Phase 3.

While streaming, the port carries nothing but data packets, so setup
commands are refused until the stream stops. `output_off()` is the
exception: it stops the stream first, because it is the safe-state path.
A garbled packet is counted, not fatal. An empty read (the library's 1 s
timeout) is counted as idle.

Firmware 1.5.0+ adds the active current range to each packet.
`firmware_streams_range` says whether the connected unit has it.

The fake replaces the library object rather than the serial port, since
the library *is* the protocol here. `tests/test_smu.py` checks that every
method of the fake exists on `minismu_py.SMU` with the same parameter
names.

## Checking the devices

```bash
uv run python -m multilbic.hardware.check --sim --home --move --lasers
```

On the Pi, `--real` (with `--smu-port` until the miniSMU has a fixed
name). It identifies each device, prints Marlin's live settings (EEPROM
can override the compiled ones), streams two seconds, and turns the
lasers off. Homing, motion and lighting lasers need the explicit flags.

Tests marked `hardware` (`tests/test_hardware.py`) run the same checks
under pytest, never moving the stage:

```bash
uv run pytest --hardware tests/test_hardware.py
```
