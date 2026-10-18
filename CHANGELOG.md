# Changelog

Newest first. Versions follow MAJOR.SESSION.PUSH, as in SMUniversal.

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
