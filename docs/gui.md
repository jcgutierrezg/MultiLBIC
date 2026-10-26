---
type: guide
title: "The window"
---

# The window

`multilbic gui` opens it, maximised, and connects to the machine;
`multilbic gui --sim` to the simulated one, with a synthetic sample on
the carriage to find. Built in Phase 5 ([plan](plan.md)); still to
come: a check on the Pi, then a run of the real machine from it.

```bash
uv run multilbic gui --sim
```

On the Pi it runs on the Pi's own monitor, started there (D6). Only one
MultiLBIC process can have the real machine at a time: a second window
or a `multilbic run` stops with "the machine is in use"
([run](run.md#run)).

## Layout

| | |
|---|---|
| header | name, version, SIMULATED, what the machine is doing; Light/Dark, Console, **STOP** |
| machine column | **Machine**: a lamp and firmware per device, Connect/Disconnect. **Stage**: Home, Centre AB, Motors off; X Y A B; the jog pad; go to a position. **Lasers**: 1-6 and Off, the one that is on filled in; the photocurrent now |
| sample column | **Calibration**: the sample's name, the three steps, Save/Load/Go to corner, and a drawing of the sample and the spot. **Run setup**: lasers, pixel, pitch, speed, bias, baseline, warm-up, range, serpentine, note, folder; the plan and estimate; **Start run** |
| run column | what the run is doing, a progress bar and the time left; a tab per laser with its map, live and then finished; Open run file..., Open folder |
| footer | the last thing that happened; everything is in the Console |

## Stop

The red **STOP**, or **Esc** anywhere in the window:

- during a run: as Ctrl+C on the command line. Motion stops at once,
  laser and SMU output go off, finished rows stay on disk;
- during a calibration move (jog, go to, trace): the move stops there,
  and the laser stays on;
- while idle: the laser goes off.

Closing the window during a run asks first, then stops the run and
waits for everything to be safe before it goes.

## Moving the stage

Nothing moves until **Home**. **Motors off** releases the steppers, so
the stage can be pushed by hand; home again afterwards.

The pad's arrows move **the spot on the sample the way they point**, as
you see it at the machine: on this machine ← is +A (or +X), ↓ is +B (or
+Y). Each button says which axis it moves. This comes from `[display]`
and `[geometry]` in `machine.toml` (`multilbic/gui/jogkeys.py`).

The keys work only while the pad has the keyboard (D19): click the pad,
and its ring turns the accent colour and says "keys on". Then:

| Key | Does |
|---|---|
| arrows, or `w a s d` | jog up, left, down, right, by the step |
| `q` | switch between XY and AB |
| `e` | next step: 0.01, 0.1, 1, 10 mm |

`w a s d` here are arrows: `w` is up on the screen. The command line's
key mode (`multilbic calibrate`) is older and maps `d` to X+, which moves
the spot left on this machine.

A key pressed while the stage is still moving is dropped, so holding
one jogs step by step instead of piling up moves. One action runs at a
time: a click while the machine is busy says so in the footer and does
nothing.

## Calibrating

The window's version of `multilbic calibrate` ([run](run.md#calibrate)):

1. **Start** homes the stage and lights the reference laser (2) over
   the AB centre. Jog until the spot is on the sample's top-right
   corner as you look at it (the photocurrent halves on an edge, in the
   dark), then **Set corner here**.
2. Type the **width** (along A) and **height** (along B) in mm, **Set
   size**.
3. **Trace the outline**: the stage places the sample as a run would
   and the spot runs round it, back to the corner. If it sat on the
   sample, **Save...**; if not, jog, set the corner and trace again.

**Load...** takes a saved calibration's corner and size without
moving; **Go to corner** puts that corner back under the beam, to check
that homing put things back where they were (`calibrate --check`).
Calibration files are offered in `~/cal` if it exists.

The drawing shows AB's safe range until a corner and size are set, then
zooms to the sample: its outline as a run places it, the corner, and
the spot (red while a laser is on), drawn as you see the stage, with a
scale bar. Jogging XY moves the spot in the drawing as it moves on the
sample; with a laser other than the reference one lit, the spot is
drawn where that laser falls.

## Setting up and starting a run

The fields are `multilbic run`'s options ([run](run.md#run)), with the
same defaults. The plan is checked as you type, with the checks `run`
makes before anything moves: a field that isn't a number, a laser with
a placeholder position (tick "allow lasers marked *" to scan it anyway),
a sample too big for AB, a pixel too fine for the speed. The problem
shows in red and **Start run** stays off until it is fixed. Above
5 mm/s, and with autoranging, a warning shows in orange.

The sample's name is the one typed in Calibration, now: it names the
run folder. **Start run** shows the plan, the estimate and the folder,
and asks (D20). The run then homes first, as `run` does, and everything
but STOP is off until it ends. Runs go to `~/multilbic-runs`
(`runs/` in the checkout when simulated).

## Watching a run

The headline says which laser and row the run is on (or homing,
warming up); the bar and the line under it how long it has taken and
how long is left. The time left is the plan's estimate until three rows
have finished, then the pace the rows actually take, plus the
baseline, warm-up and laser switch of each laser still to come.

Each laser has a tab. While it scans, the tab shows the **live map**:
each row binned as it finishes, with the laser-off baseline subtracted
and mains removed, as the finished map does, but **not corrected for
the serpentine shift** (D18), so edges look jagged where forward and
reverse rows sit a little apart. When the laser ends, the **finished
map**, built from its file exactly as the PNG beside it, takes its
place, and the caption gives the shift it found and removed. Both are
drawn as you see the cell, with the corner marked, on white paper in
both modes.

A map with more pixels than the screen can show (over 600 a side) is
binned into blocks of pixels as it arrives, so a redraw costs the same
for any map; the file keeps every sample. Redraws happen at most twice a
second.

**Open run file...** draws an earlier run's map (any `laserN_*.csv`)
in a tab of its own; it is off during a run, since mapping a big file
is heavy work. **Open folder** opens the last run's folder.

## Lasers and the photocurrent

A laser button lights that laser; Off turns them all off. Lasers whose
position in `machine.toml` is still a placeholder are marked `*`.
During a run the buttons are locked, and the one the run has lit is
filled.

Once homed, the photocurrent is read twice a second while the machine
is idle: in the dark, an edge is where it halves. A run ends with the
SMU output off, so readings stop until the next Home.

## How it is built

The window never touches a device. `multilbic/gui/worker.py` owns them
on one thread; the window calls it and reads its events every 50 ms
(SMUniversal rule 8). Theme, console and the thread guard come from
SMUniversal; the accent is MultiLBIC's own teal.
