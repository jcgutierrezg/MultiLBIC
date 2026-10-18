# Changelog

Newest first. Versions follow MAJOR.SESSION.PUSH, as in SMUniversal.

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
