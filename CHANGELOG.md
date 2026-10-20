# Changelog

Newest first. Versions follow MAJOR.SESSION.PUSH, as in SMUniversal.

## 0.1.8 - Lasers checked; settle time from machine.toml

- Lasers checked on the bench:
  - each of the six lights alone, the right colour, at the right servo
    angle, so this Xiao drives them;
  - the "two at once" seen in the fast probe never showed up one at a
    time;
  - servo settle on the worst 120° swing is stable at 1000 ms and slides
    at 500 ms.
- Decision D10: the settle stays **2000 ms**, now in `machine.toml`
  (`[laser_board] settle_ms`, validated to the firmware's 0–10000 ms).
  `LaserBoard.open()` applies it whenever the board reports something
  else, because the firmware forgets a runtime value on power-up. The
  fake laser board records what it receives; tests cover both cases.

## 0.1.7 - A/B ceiling raised to 6 mm/s

- `machine.toml`: A/B `max_feed_mm_s` is 6.0 (decision D9). It matches
  the board's EEPROM, and A ran smoothly at 3–6 mm/s. A and B share it,
  being mechanically identical.
- The Marlin probe's stop test runs at a fixed 2 mm/s, so its results
  stay comparable whatever the ceiling. Tests updated for the new
  ceiling.

## 0.1.6 - Motion measured; no moves lost after a stop

- First homing and motion run on the machine:
  - homing takes 33.5 s;
  - A/B speeds are exact at 1 and 2 mm/s;
  - each move carries 113–135 ms, which is Marlin's 100 ms first-move
    delay plus acceleration;
  - Stop acts at once.
- Found on it: for 1 s after `M410`, Marlin silently drops new moves and
  reports their target as the position. `Marlin.quickstop()` now makes
  the next move wait with `M400` first. The fake Marlin models the
  lockout and keeps its reported and planned positions apart; two tests
  cover it.

- Speed trials on A at 3, 4, 5 and 6 mm/s: every speed was reached
  (model plus 0.1 s), and by eye and ear all were smooth. B was not
  tested above 2 mm/s. The motion run repeated within a few ms.

## Earlier on 0.1.5

- Contacted-cell noise measured:
  - lights on: −165 µA background, 1.7 µA RMS, mostly slow drift plus
    100 Hz flicker;
  - lights off and covered: −0.83 µA, 0.12 µA RMS, 81 % slow drift at
    0.2–0.7 Hz, 17 % at 50 Hz.
- The drift shares its band with map features, so open decision D8
  (enclosure and baselines, or laser chopping with a software lock-in)
  is added to the plan.
- The Xiao and the miniSMU needed a replug after every Pi boot. Recorded
  under "USB at boot" in `docs/hardware.md`.

## 0.1.5 - Bulk stream reader for the miniSMU

- `SmuStream` reads the miniSMU's serial port itself: everything waiting
  in one call, split into packets by `parse_packet()`. The library's
  per-line `readline()` read one byte per system call and fell behind
  the stream on the Pi; a bulk read kept up at 1190 packets/s on the
  bench. The per-line path stays for network connections only.
- `StreamSample.extra` keeps fields after the fourth (1.4.6 already
  sends a fifth). `StreamStats` records which reader ran and any port
  failure.
- The fake miniSMU now streams bytes through a fake serial port in the
  measured format, with whole-millisecond stamps and an optional rate
  error. Tests cover packets split across reads, the per-line fallback,
  and a delivered rate that differs from the requested one.
- On the bench, the bulk reader:
  - read 1009 Hz at 1000 requested, and 1409 Hz (the instrument's
    ceiling) at 2000;
  - kept the 60 s backlog flat (52 ms median arrival latency);
  - streamed both channels cleanly.
- Found while running it:
  - periodic stamp bunching (~every 100 ms);
  - a clock offset to the Pi: +306 ppm over 60 s, but about −95 ppm in
    two 10 s fits, so it needs longer runs to pin down;
  - open-lead noise of ~14.5 nA RMS, repeatable, of which **89 % is
    50 Hz mains pickup**.
  - All recorded in `docs/hardware.md`. Architecture: notch or
    whole-cycle averaging in Phase 3's binning.

## 0.1.4 - SSH setup fixes in the runbook

- `docs/bench.md` explains `ssh-keygen`'s questions: keep the default
  file, leave the passphrase empty (Claude connects without a terminal
  to type one), and keep an existing key.
- It also addresses the Pi as `<name>.local` (avahi) rather than by IP,
  which changes between networks, and explains why `hostname -I` shows
  several addresses.
- Laser firmware 2.0.0 compiled and flashed. The board answers
  `MultiLBIC-Laser,2.0.0` over SSH.
- All four USB devices identified by serial number. The laser Xiao is
  line 3 of `Serials.txt`; line 1 is the retired instrumentation Xiao.
- `machine.toml` names the Pi's ports by `/dev/serial/by-id/` path,
  which is stable across replugging and needs no udev rules, instead of
  the old rules' `/dev/SKR`-style names.
- Runbook: clone with `--branch` (a plain clone lands on `main`, which
  has no `setup.sh` yet). Warns that the first install downloads over
  100 MB.
- First bench session over SSH (no motion, no lasers):
  - all four devices answer, and the hardware tests pass;
  - the running Marlin settings differ from compiled: A/B at 6 mm/s,
    600 mA, StallGuard 130;
  - the miniSMU streams up to ~1.2 kHz with whole-millisecond stamps,
    but its delivered rate is not the requested one, and per-line
    reads can't keep up on the Pi (bulk reads can);
  - noise at 0 V is ~1.5 nA RMS on the low ranges.
  - Findings are in `docs/hardware.md`.
- First SSH check of the Pi recorded:
  - the SKR and the TFT35's FTDI adapter identified;
  - there are no udev rules on the Ubuntu install;
  - the `sudo` steps are yours, because `sudo` needs a password.
- The miniSMU firmware upgrade is optional for the first session.
  Undalogic's updater fails server-side (HTTP 500), and 1.4.6 streams,
  just without the current range in each packet.

## 0.1.3 - The Pi runs Ubuntu 24.04

Docs and `deploy/pi/setup.sh` assumed Raspberry Pi OS. Now:

- SSH setup is `openssh-server` + `systemctl`, with no default `pi` user;
- git and curl are installed first, and `setup.sh` checks for them;
- `setup.sh` warns about ModemManager (probes `/dev/ttyACM*`) and brltty
  (claims CH340 adapters), without changing either;
- Python 3.12 is what Ubuntu ships, so the Pi uses a uv-managed 3.14.

## 0.1.2 - Bench probes for the first session

- `multilbic/bench/`: one probe per device (`ports`, `marlin`, `laser`,
  `smu`), each writing a JSON report stamped with commit and firmware.
  Motion and lasers only with explicit flags.
  - Marlin: running settings, round-trip time, a time-against-distance
    fit for real speed and fixed overhead, how quickly `M410` acts,
    keepalive spacing, and optional runtime speed trials (restored
    afterwards, never saved).
  - Laser board: switching and settle times.
  - miniSMU: raw packet format, achieved rates, timestamp resolution,
    two channels, clock drift and arrival latency, noise at 0 V per
    current range.
- Every probe also runs against the simulators, tested in CI.
- `deploy/pi/setup.sh` sets up or updates the Pi checkout.
  `docs/bench.md` covers SSH setup and the session order.
- `Marlin.use_limits()` for probes that change limits at runtime. The
  fake Marlin learned `M203` and `M122`, and the fake miniSMU learned
  current ranges.

## 0.1.1 - Phase 2: device layer and simulators

- `multilbic/hardware/marlin.py`: Marlin client.
  - Line numbers and checksums, with each `ok` matched to its command;
    resend handling.
  - `busy:` keepalives extend waits, and Stop (`M410`) jumps the queue.
  - Feed and range limits are enforced before Marlin would silently
    clamp them; absolute moves need a trusted (homed) position.
- `multilbic/hardware/laser.py` and laser firmware 2.0.0:
  - one reply per command, identification, state and angle queries;
  - a settle time that can be set, skipped when the servo is already
    in place; no servo park on `LASER 0`.
  - The firmware is not compiled or flashed yet.
- `multilbic/hardware/smu.py`: SMUniversal's miniSMU driver for setup,
  and streaming straight from `minismu_py`. Samples keep both the
  instrument's timestamp and the host's.
- Simulators for all three (`multilbic/sim/`), driven through the real
  drivers over the same text. The fake Marlin models planner timing
  (per-axis limits, trapezoids, 100 ms first-move delay) and injects
  faults.
- `multilbic/clock.py`: one time source, scaled in tests so simulated
  moves run 100× faster.
- `python -m multilbic.hardware.check` (`--sim` / `--real`) and
  `--hardware` pytest tests for the Pi.
- Docs: `docs/devices.md`. Hardware notes on `M114` and on releasing the
  motors.

## 0.1.0 - Phase 0: foundations

- uv project on Python 3.14. SMUniversal is pinned to a commit as a git
  dependency, and its instrument libraries (pyvisa, pyvisa-py, pyusb,
  libusb-package, ni-gpib-usb-hs, scipy) are dropped with uv overrides.
  `tests/test_dependencies.py` checks that they stay absent and that the
  SMUniversal modules MultiLBIC uses still import.
- `multilbic/config/`: the machine description moved out of the code into
  `machine.toml` (stages, lasers, ports per platform), loaded strictly
  into frozen dataclasses.
- Gates: pytest, ruff and mypy (boundaries only). CI on Windows, Ubuntu,
  and Ubuntu ARM with a uv-managed Python as the stand-in for the Pi.
- Docs: `docs/development.md` and Pi install steps in `deploy/pi/`.

## Initial import

- Folder reorganised ahead of the rewrite:
  - the old scripts moved to `legacy/` and two byte-identical copies
    deleted;
  - laser board firmware moved to `firmware/laser/`;
  - Marlin reduced to its two changed config files in `firmware/marlin/`
    (checked against upstream 2.1.2.4: nothing else differed);
  - the USB serial list moved to `deploy/pi/`.
- Planning docs: `docs/hardware.md`, `docs/architecture.md`,
  `docs/plan.md`.
