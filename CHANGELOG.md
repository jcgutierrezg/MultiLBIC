# Changelog

Newest first. Versions follow MAJOR.SESSION.PUSH, as in SMUniversal.

## Unreleased

- Folder reorganised ahead of the rewrite:
  - the old scripts moved to `legacy/` and two byte-identical copies
    deleted;
  - laser board firmware moved to `firmware/laser/`;
  - Marlin reduced to its two changed config files in `firmware/marlin/`
    (checked against upstream 2.1.2.4: nothing else differed);
  - the USB serial list moved to `deploy/pi/`.
- Planning docs: `docs/hardware.md`, `docs/architecture.md`,
  `docs/plan.md`.
