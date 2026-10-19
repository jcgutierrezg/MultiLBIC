---
type: guide
title: "Development"
---

# Development

Day-to-day work happens on Windows against the simulators. The Pi only
needs the code once something has to touch the real machine. Pi setup is
in [`deploy/pi/`](../deploy/pi/README.md).

## Setup

Needs [uv](https://docs.astral.sh/uv/) and a Python 3.14 install. uv
prefers the system interpreter (`python-preference = "system"`) and
falls back to its own if there is none.

```bash
uv sync
```

That installs MultiLBIC, the pinned SMUniversal commit with only what
the miniSMU needs, and the dev tools (pytest, ruff, mypy).

## The gates

CI runs all three, and a branch is ready for a PR when they pass
locally:

```bash
uv run pytest
```

```bash
uv run ruff check .
```

```bash
uv run mypy
```

`mypy` with no arguments checks the file list in `pyproject.toml`: the
module boundaries, not the whole tree, as in SMUniversal.

CI ([`.github/workflows/tests.yml`](../.github/workflows/tests.yml)) runs
the tests on:

- Windows and Ubuntu, with system Pythons;
- **Ubuntu on ARM with a uv-managed Python**, the setup the Pi has.

A failure that appears only there is a Pi problem found early.

## Without the machine

Every device has a simulator, so the whole device layer runs on Windows:

```bash
uv run python -m multilbic.hardware.check --sim --home --move --lasers
```

Tests marked `hardware` are skipped unless pytest gets `--hardware`,
which is only for the Pi. See [devices](devices.md). The bench probes
(`multilbic/bench/`) also run with `--sim`; on the machine they follow
[bench](bench.md).

## Workflow

- Work on a branch. The PR is merged on GitHub; nothing is merged to
  `main` locally.
- Versions are MAJOR.SESSION.PUSH. The version in `pyproject.toml` is
  bumped in the commit that is pushed, and `CHANGELOG.md` gets an entry
  for it.
- Plan and decisions: [plan](plan.md). Design: [architecture](architecture.md).

## Moving the SMUniversal pin

SMUniversal is pinned to a commit in `[tool.uv.sources]`. To move it:

1. Change `rev`, then run `uv lock`.
2. Run the tests. `tests/test_dependencies.py` is the guard: it checks
   that the dropped instrument libraries are still absent, and that
   every SMUniversal module MultiLBIC uses still imports without them.
3. Adding an import from SMUniversal? Add the module to `USED` in that
   test first.

## The machine file

Calibrated values (laser positions, servo angles, AB range, feeds,
ports) live in
[`multilbic/config/machine.toml`](../multilbic/config/machine.toml), not
in the code.

`multilbic.config.load()` reads it into frozen dataclasses. Unknown keys,
missing keys and impossible values are refused with the key named, so
a typo can't silently fall back to a default.

Where the Pi's own calibrated copy lives is decided at commissioning
(Phase 6).
