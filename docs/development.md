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
- **Ubuntu on ARM with a uv-managed Python**: aarch64 Linux, as the Pi
  (which runs deadsnakes' 3.14 for its Tk's smooth fonts, D21).

A failure that appears only there is a Pi problem found early.

## Without the machine

Every device has a simulator, so the whole device layer runs on Windows:

```bash
uv run python -m multilbic.hardware.check --sim --home --move --lasers
```

The window runs against it as well, with a synthetic 2 × 1 mm sample
whose top-right corner is at A 15.2, B 16.1 with XY under laser 2
([gui](gui.md)):

```bash
uv run multilbic gui --sim
```

The command line runs against the simulated machine too
([run](run.md)):

```bash
uv run multilbic calibrate --sim --sample test
```

```bash
uv run multilbic run test.json --sim --lasers 1,2,3 --pixel 0.01 --pitch 0.05
```

A whole scan of a synthetic sample, with latency, backlash and clock
drift injected, writes a run file and a PNG and prints how far the map
is from the truth ([scan](scan.md#the-simulated-scan)):

```bash
uv run python -m multilbic.sim.scan --height 0.4 --speedup 2
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

## The window's tests

`tests/test_gui.py` drives the real window against the simulator:
clicks are `invoke()`, keys `event_generate`, waiting is pumping Tk
until the worker is idle and the window has seen its events. Three
things learned the hard way:

- **One Tk per test module.** Starting Tcl afresh for every test failed
  now and then on Windows ("couldn't read file init.tcl"); each test
  gets a `Toplevel` of one shared root instead.
- **Close the worker in `finally`.** Its thread is not a daemon, on
  purpose (a crashed window must not cut a run off mid-command), so a
  test that fails before closing it leaves pytest hanging.
- **Keys go to the focused widget.** A test gives a widget the keyboard
  with `focus_force()` before sending it keys, and skips if the window
  manager refuses.

The fixture installs SMUniversal's Tk thread guard and fails the test
if any worker thread read or set a Tk variable. The window's logic that
needs no Tk (the worker, the run form, the live map, the jog keys, the
laser colours) is tested without a window, in `test_worker.py`,
`test_runform.py`, `test_livemap.py`.

Linux needs a display: CI runs the tests under `xvfb`. Over SSH the Pi
has none, so there the window tests skip; to run them on the Pi's own
screen from SSH:

```bash
DISPLAY=:0 XAUTHORITY=$(ls /run/user/1000/.mutter-Xwaylandauth.*) ~/.local/bin/uv run --no-sync pytest tests/test_gui.py
```
