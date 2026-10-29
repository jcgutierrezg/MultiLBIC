---
type: guide
title: "Running a map"
---

# Running a map

From a sample on the stage to its maps, from the command line (Phase 4).
The window does the same with buttons ([gui](gui.md)); what is said here
about placement, the options, Stop, faults and the run folder holds for
both. How a map is computed is in [scan](scan.md); the bench steps that
check all this on the machine are in [bench](bench.md#phase-4-first-maps).

```bash
uv run multilbic calibrate --sample cell-7 --out ~/cal/cell-7.json
uv run multilbic run ~/cal/cell-7.json --lasers 1,2,3 --pixel 0.01 --pitch 0.05
```

Add `--sim` to either for the simulated machine (Windows is fine).

## Where the sample is: XY placement

XY carries the whole AB gantry, so moving XY moves the sample under the
beam just as AB does. Calibration is done in **XY**, under one laser,
with AB at its centre. For each laser of a run, XY puts the sample's
centre at the AB centre under that laser, and AB rasters around it.
The sample can sit anywhere on the carriage, and every map gets AB's
full range (up to about 34 mm, less the run-up).

`machine.toml`, `[geometry]`:

| Key | Meaning |
|---|---|
| `reference_laser` | the laser calibration is done under (2) |
| `x_along`, `y_along` | which AB axis each XY axis moves the sample along, and which way: `"+A"` means X up moves it like A up. **Checked on the bench before any real run** (`directions_measured`) |
| `xy_take_up_mm`, `ab_take_up_mm` | every placing move ends moving up from at least this far below, so backlash is always taken up the same way (Marlin lists 0.2 mm on X/Y, uncorrected) |
| `ab_backlash_mm` | A/B backlash once measured. Calibration reads AB after moving up, half the backlash above the stage; aligned maps are shifted by half of it to agree |

How well maps from different lasers line up rests on each laser's
`xy_centre_mm`. Lasers 1–3 were measured once; 4–6 are placeholders, so
`run` refuses them without `--allow-unmeasured`. The channel-2
photodiode measures them properly in Phase 6.

## `calibrate`

Interactive, at the machine. It homes, puts the reference laser over the
AB centre and lights it, and gives you a prompt:

| Command | Does |
|---|---|
| `keys` | jog with single keys (below) |
| `x+0.5`, `y-1`, `a+0.01`, `b-0.02` | jog that axis by that many mm (at most 20) |
| `x+`, `a-` | jog by the current step |
| `step 0.05` | set the step |
| `move x=70 y=65 a=17.5` | go to a position, any axes |
| `centre` | AB back to its centre |
| `where` | print X Y A B |
| `laser 2`, `off` | light a laser, or none |
| `read` | the photocurrent now: in the dark, an edge is where it halves |
| `here` | record the corner |
| `size 10 10` | width along A and height along B, mm |
| `trace` | place the sample as a run would and run the spot round its outline, ending on the corner |
| `ranges 1,2,3 [bias]` | each laser's current range on this sample (D25): XY places the sample as a run will for that laser, the laser comes on, and the stage runs a coarse grid over the sample (3 lines along A and 3 along B, at 2 mm/s) reading the photocurrent on autorange; the range is the smallest holding 3x the brightest reading. Uses the run's bias if you give it. About 15 s a laser on a 2 mm sample. Ends with the reference laser back on the corner. `save` keeps the ranges with the calibration |
| `save [file]` | write the calibration (JSON), with its checked ranges |
| `help`, `quit` | |

**Key mode** (`keys`), no Enter needed:

| Key | Does |
|---|---|
| `d` / `a` | X up / down (A in AB mode) |
| `w` / `s` | Y up / down (B in AB mode) |
| `q` | switch between XY and AB |
| `e` | step 0.1 → 1 → 10 mm, then back to 0.1 |
| Esc, Enter, Ctrl+C | back to typed commands |

It starts in XY at 0.1 mm. Keys pressed while the stage is moving are
dropped, so holding a key jogs step by step rather than queueing moves.
For finer than 0.1 mm, leave key mode and type a jog (`a+0.01`). On
this machine `d` (X up) moves the stage to the right as you stand at it,
as the window's right arrow does; `w` (Y up) moves it away from you, up
in the reference photo's view.

**The corner** is the one the sample extends from towards +A and +B:
on this machine, the sample's **top-right corner** as you look at the
stage: +A moves the stage right, so the spot runs left over the sample,
and +B moves the stage up, so the spot runs down
([hardware](hardware.md#mechanics)).
Every jog ends moving up, like every move a run makes. Jog XY to get
close, fine-tune with XY or AB, `here`, `size`, `trace`; if the outline
sits on the sample, `save`.

`calibrate --check FILE` homes and puts a saved corner back under the
beam. If the spot isn't on the corner, homing moved things: jog back,
`here`, `save`.

## `run`

Reads a calibration, checks everything that can be checked **before
anything moves** (lasers exist and are measured, XY can reach each
placement, every row fits AB's safe range, the pixel isn't too fine for
the speed), prints the plan and an estimate, then asks to start. It
homes first, since another process may have released the motors or the
board may have restarted since calibration.

| Option | Default | |
|---|---|---|
| `--lasers 1,2,3` | (required) | in this order |
| `--pixel 0.01` | (required) | mm along A |
| `--pitch 0.05` | (required) | mm between rows |
| `--speed 4` | 4 mm/s | stay at 5 or below (D9); 4 is bench-proven (D27) |
| `--bias 0` | 0 V | |
| `--current-range 25u` | checked, else 25 µA | fixed SMU range, one for all lasers (`25u`), one per laser (`1=650u,2=25u,3=650u`), or both (`25u,1=650u`: 650 µA for laser 1, 25 µA for the rest). Ranges: `1u`, `25u`, `650u`, `15m`, `180m`, `auto`. **Without it, each laser uses the range checked for this sample at calibration** (`ranges` above), and 25 µA if it wasn't checked; the plan printed before the start says which. Given, it applies as written. Lasers can be 100x apart in brightness on one sample (on the test cell lasers 1 and 3 need 650 µA, laser 2 25 µA), so they need their own (D15 revised). The SMU's current limit is set to the range's full scale (1 mA when autoranging). Autoranging drops 10–15 ms of samples at every range switch; a clipping range starts that laser again one range up (below) |
| `--baseline 3` | 3 s | laser-off baseline per laser |
| `--warmup 60` | 60 s | laser on, stage still, before the first row, so its output settles (laser 2 drifted 2x after switch-on); recorded in the file as row −2. `0` skips it |
| `--one-direction` | serpentine | no serpentine alignment then |
| `--allow-unmeasured` | | lasers with placeholder positions |
| `--no-step-up` | | a laser whose range clips fails the run, instead of starting again one range up (below) |
| `--note "room lights on"` | | free text in every file header and `run.json` |
| `--out DIR` | `~/multilbic-runs` (`runs/` with `--sim`) | |
| `--yes` | | don't ask; needed without a terminal |
| `--sim`, `--speedup 5` | | the simulated machine, its speed |

On the Pi, so a dropped SSH connection doesn't end it:

```bash
nohup uv run --no-sync multilbic run ~/cal/cell-7.json --lasers 2 --pixel 0.01 --pitch 0.05 --speed 1 --yes > ~/run.log 2>&1 &
```

**Stop** is Ctrl+C, or `kill -INT <pid>` / `kill <pid>` for a run under
`nohup`. Motion stops at once (`M410`); the laser, stream and SMU output
go off; the current laser's file is marked `stopped` with every finished
row in it; later lasers don't start. The row in progress is not written:
its end is no longer where the motion model says.

**Faults** end the run the same way, marked `failed: <why>`: a Marlin
timeout or halt, a laser board that stops answering (the Xiao still
drops off USB now and then), a stream that stalls, reports a read error,
or delivers less than half a row's samples.

**A range that clips** (a row, or the baseline, reaching the end of its
fixed range) doesn't end the run (D26): that laser stops as for a fault,
its attempt is kept as `laserN_<nm>nm_<range>.csv` with the status
`clipped`, and its whole map starts again one range up (1 µA, 25 µA,
650 µA, 15 mA, 180 mA), with a fresh baseline and no second warm-up. The
event log has a `laser_step_up`, the final file's header lists the
clipped attempts, and `run.json` gives each laser's final range.
Clipping at 180 mA, or with `--no-step-up`, fails the run as before.

**One process at a time.** `calibrate`, `run` and the GUI take the
machine lock before opening the real machine
(`multilbic/run/devices.py`), so a second one stops with "the machine
is in use by another MultiLBIC process" instead of fighting over the
ports. The operating system drops the lock when the process ends, even
by a crash. Simulated machines take no lock.

## The run folder

```text
~/multilbic-runs/20261021T093000Z_cell-7/
    run.json            what was asked, each laser's plan and XY, the outcome
    calibration.json    the calibration used
    events.jsonl        run and laser start/end, with status (SMUniversal's EventLog)
    laser2_519nm.csv    the run file (format: scan.md)
    laser2_519nm.png    its map, built from that file alone
    laser1_444nm_25u.csv  (only if laser 1 clipped at 25 uA) the attempt
                          that clipped, before it started again one range up
```

A map is built from its file alone, so it can be rebuilt later with
better calibration: `multilbic map <run folder>/laser2_519nm.csv` draws
it again (`multilbic.scan.mapping.build_map`). PNGs are turned to match
how the cell looks at the machine (`[display]` in `machine.toml`): the
calibration corner is marked, at the top right.

## `sync-check`: the sync error on one edge (Phase 6)

```bash
uv run multilbic sync-check ~/cal/stdtest-redge.json --laser 2 \
    --window 0,0.8,0.5,1.5 --speeds 1,4,5 --yes
```

Measures what the rows' timing gets wrong, against positions that
involve no timing. In one session, homing once and placing XY once
(homing is only known to repeat to about 0.1 mm, more than what is being
measured):

1. **step-and-measure** over the patch (`--window u0,u1,v0,v1`, mm in
   the sample's frame): at each point, `--step` apart along A, the stage
   stops, waits `--settle` s, and the SMU is averaged for `--dwell` s
   (rounded up to whole mains periods). Every point is reached moving up
   along A, as in a forward row;
2. **continuous rows** over the same patch at each of `--speeds`, at
   the same B as the step rows, written by the same code as `run`;
3. **step-and-measure again** (unless `--no-repeat`): the difference is
   the drift over the session.

The patch should hold one straight edge crossing the rows, like the
test cell's right edge. Step-and-measure takes about half a second a
point: 81 points by 10 rows is about 7 minutes a pass. The range is the
calibration's checked range for the laser, else 25u (`--current-range`).
`--sim` puts a straight edge in the middle of the patch on the
simulated machine, with an SMU that stamps 18.6 ms late (`--sim-lag-ms`).

The edge is fitted in every row (an error function: its 50 % point and
10-90 % width, `multilbic.scan.edges`). Against step-and-measure,
forward rows sit `L v` away and reverse rows `-(beta + L v)`, so across
two speeds or more it gives:

- **`L`**, the timing error: positive if samples are stamped after they
  were measured;
- **the A backlash `beta`**, which the serpentine alignment can't tell
  from timing (it sees `beta + 2 L v`);
- per pass, the shift from the edges against the map's own alignment;
- the spot's 10-90 % width from step-and-measure.

```text
~/multilbic-runs/20261029T100000Z_sync_stdtest-redge/
    sync.json        what was asked, the passes, the result
    p1_steps.csv     step-and-measure (a run file with `mode: steps`)
    p2_1mm_s.csv     rows at 1 mm/s, and its .png; then 4 and 5 mm/s
    p5_steps.csv     step-and-measure again
```

## `edges`: the edge in every row

```bash
uv run multilbic edges <run folder>/laser2_519nm.csv
uv run multilbic edges <sync check folder>
```

For a run file, the edge's position and 10-90 % width in each row, the
forward/reverse shift from the edges, and what the map's alignment
said. For a sync check's folder, its result worked out again from the
files. `--a-range lo,hi` (machine A, mm) keeps the fits to one edge
when a row crosses several.

## `read`: one channel, dark and under lasers, no motion

```bash
uv run multilbic read                      # channel 2, dark only
uv run multilbic read --lasers 1,2,3 --out ~/cal/pd-first.json
```

For the photodiode on channel 2 (Phase 6 step 8): every laser off, a
dark reading, then each laser in `--lasers` on in turn, read, and off
again. For each it prints the mean, the scatter, the current above dark
and its sign, and the fixed range a scan would pick (the smallest
holding 3x the reading). A laser that barely rises above the dark
scatter is flagged: the photodiode isn't under it, or its lead isn't on
that channel.

**The stage does not home or move.** Put the photodiode under the laser
first (jog in the window), then close the window: it holds the machine
lock. Single readings on autorange, 0 V unless `--bias`, `--seconds`
each (2), after `--settle` s with the laser on (2): long enough to get
past the first flicker, not a warm-up. It asks before lighting a laser
unless `--yes`. Ctrl+C switches every laser and the channel off.
`--channel 1` reads the cell the same way.

It prints the median and a robust scatter. Readings far from the median
(autorange can return one wild value as it switches) are counted and
left out of the mean, and the file keeps every value. A laser near 1 mA,
the limit on autorange, is read on a fixed range instead:
`--current-range 15m`, whose full scale is also its current limit.
