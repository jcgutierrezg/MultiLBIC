---
type: guide
title: "Diagnostics"
---

# Diagnostics

Commands for measuring the machine rather than a sample: a reading with
no motion, the timing error on one edge, the edge in every row of a
map, and the device probes. Each takes the machine lock like `run`, so
close the window first. Those that move or light a laser say so and
ask, unless `--yes`.

## `read`: one channel, dark and under lasers, no motion

```bash
uv run multilbic read                      # channel 2, dark only
uv run multilbic read --lasers 1,2,3 --out ~/cal/pd-first.json
```

Every laser off, a dark reading, then each laser in `--lasers` on in
turn, read, and off again. For each it prints the median, a robust
scatter, the current above dark and its sign, the voltage, and the fixed
range a scan would pick (the smallest holding 3× the reading). A laser
that barely rises above the dark scatter is flagged: the photodiode
isn't under it, or its lead isn't on that channel. `--channel 1` reads
the cell the same way.

**The stage does not home or move.** Put the photodiode under the laser
first (**Go to photodiode** in the window), then close the window.
Single readings on autorange, 0 V unless `--bias`, `--seconds` each (2),
after `--settle` s with the laser on (2): past the first flicker, not a
warm-up. Readings far from the median (autorange can return one wild
value as it switches) are counted and left out of the mean; the file
keeps every value.

- **A laser near 1 mA**, autorange's limit, is read on a fixed range:
  `--current-range 15m`, or per laser, `--current-range
  1=15m,2=650u,3=15m`. A laser on a range of its own gets its own dark
  on that range. "Above dark" is exact only on a fixed range.
- **The voltage** at 0 V should be within a few mV; more is channel 2's
  offset state ([smu](hardware/smu.md#the-channel-2-offset-state)).
- **`--at N=X,Y,A,B`**, once per laser, reads each where the photodiode
  is under it: **the stage homes first**, then goes to each laser's
  place before the laser comes on. Ctrl+C stops the stage as well.

## `sync-check`: the sync error on one edge

```bash
uv run multilbic sync-check ~/cal/<edge>.json --laser 3 \
    --window <u0>,<u1>,<v0>,<v1> --speeds 1,4,5 --yes
```

Measures what the rows' timing gets wrong, against positions that
involve no timing, in one session (homing once and placing XY once):

1. **step-and-measure** over the patch (`--window u0,u1,v0,v1`, mm in
   the sample's frame): at each point, `--step` apart along A, the stage
   stops, waits `--settle` s, and the SMU is averaged for `--dwell` s
   (rounded up to whole mains periods). Every point is reached moving up
   along A, as in a forward row;
2. **continuous rows** over the same patch at each of `--speeds`, at
   the same B, written by the same code as `run`;
3. **step-and-measure again** (unless `--no-repeat`): the difference is
   the drift over the session.

The patch should hold one straight edge crossing the rows, and nothing
else; about 7 minutes a step-and-measure pass for 81 points by 10 rows.
The range is the calibration's checked range for the laser, else 25 µA
(`--current-range`). `--sim` puts a straight edge in the middle of the
patch, with an SMU that stamps 18.6 ms late (`--sim-lag-ms`).

The edge is fitted in every row (an error function: its 50 % point and
10–90 % width, `multilbic.scan.edges`). Forward rows sit `L v` from
step-and-measure and reverse rows `-(beta + L v)`, so two speeds or
more give:

- **`L`**, the timing error: positive if samples are dated after they
  were measured;
- **the A backlash `beta`**, which the serpentine alignment can't tell
  from timing (it sees `beta + 2 L v`);
- per pass, the shift from the edges against the map's own alignment;
- the spot's 10–90 % width from step-and-measure.

The last result is in [timing](hardware/timing.md#the-sync-check).

```text
~/multilbic-runs/<stamp>_sync_<sample>/
    sync.json        what was asked, the passes, the result
    p1_steps.csv     step-and-measure (a run file with `mode: steps`)
    p2_1mm_s.csv     rows at 1 mm/s, and its .png; then 4 and 5 mm/s
    p5_steps.csv     step-and-measure again
```

## `edges`: the edge in every row

```bash
uv run multilbic edges <run folder>/laser3_652nm.csv
uv run multilbic edges <sync check folder>
```

For a run file, the edge's position and 10–90 % width in each row, the
forward/reverse shift from the edges, and what the map's alignment
said. For a sync check's folder, its result worked out again from the
files. `--a-range lo,hi` (machine A, mm) keeps the fits to one edge when
a row crosses several.

## The device probes

One device at a time, each writing a report to
`~/MultiLBIC/bench-results/<time>_<probe>_real.json`, stamped with the
commit and firmware (the folder is ignored by git). Each runs with
`--sim` too. Steps marked **at the machine** move the stage or light a
laser.

| Command | Moves / lights | What it answers |
|---|---|---|
| `python -m multilbic.bench.ports --real` | no | which port and serial number is which board |
| `python -m multilbic.hardware.check --real` | no | every driver talks to its device; Marlin's live settings |
| `pytest --hardware tests/test_hardware.py` | no | the same, under pytest |
| `python -m multilbic.bench.marlin --real` | no | EEPROM settings, driver status, round trip |
| `python -m multilbic.bench.marlin --real --home --motion` | **at the machine** | real A/B speed, move overhead, Stop, keepalive |
| `python -m multilbic.bench.marlin --real --home --motion --speeds 3,4,5 --speed-span 1,39` | **at the machine** | speed trials over the travel; note what you see and hear |
| `python -m multilbic.bench.laser --real [--lasers]` | `--lasers` lights them | firmware, angles, switching and settle times |
| `python -m multilbic.bench.smu --real --port <smu port> --load "<what is connected>"` | no | stream rates, stamps, clock drift, noise per range (the port is the `smu` one in `machine.toml`) |

A probe that fails partway still saves what it had, and a Marlin probe
that fails mid-move sends a quickstop first.
