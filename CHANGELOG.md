# Changelog

Newest first. Versions follow MAJOR.SESSION.PUSH, as in SMUniversal.

## 0.1.4 - SSH setup fixes in the runbook

- `docs/bench.md` explains `ssh-keygen`'s questions: keep the default
  file, leave the passphrase empty (Claude connects without a terminal
  to type one), and keep an existing key.
- It also addresses the Pi as `<name>.local` (avahi) rather than by IP,
  which changes between networks, and explains why `hostname -I` shows
  several addresses.

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
