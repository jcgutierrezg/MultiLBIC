---
type: guide
title: "The window"
---

# The window

`multilbic gui` opens it, maximised, and connects to the machine;
`multilbic gui --sim` to the simulated one, with a synthetic sample on
the carriage to find. Being built in Phase 5 ([plan](plan.md)): the
machine column is done; the sample and run columns come next.

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
| sample column | calibration and run setup (step 5) |
| run column | live map, progress, Start (step 6) |
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

## Lasers and the photocurrent

A laser button lights that laser; Off turns them all off. Lasers whose
position in `machine.toml` is still a placeholder are marked `*`.

Once homed, the photocurrent is read twice a second while the machine
is idle: in the dark, an edge is where it halves. A run ends with the
SMU output off, so readings stop until the next Home.

## How it is built

The window never touches a device. `multilbic/gui/worker.py` owns them
on one thread; the window calls it and reads its events every 50 ms
(SMUniversal rule 8). Theme, console and the thread guard come from
SMUniversal; the accent is MultiLBIC's own teal.
