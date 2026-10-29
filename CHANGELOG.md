# Changelog

Newest first. Versions follow MAJOR.SESSION.PUSH, as in SMUniversal.
From Phase 4 on, the middle number is the phase.

## 0.6.8 - Reading the photodiode with no motion

- `multilbic read` reads one SMU channel (2, the photodiode, by
  default) with every laser off, then under each laser asked for, one
  at a time, and prints the mean, scatter, current above dark, its sign
  and the range a scan would pick. The stage doesn't home or move; it
  asks before lighting a laser ([run](docs/run.md)). The machine can now
  be opened with the SMU on channel 2.
- The simulator's channel 2 reads a fixed 40 uA under any lit laser, a
  stand-in until step 4 puts a chip on the plate.
- The new stage is on the machine: lasers 1-3 just reach the
  photodiode, it sits 1 cm lower (lasers 1-3 refocused, so `spot_um`
  is out of date), and a new test cell is contacted with silver paint
  underneath ([hardware](docs/hardware.md)). The bench runbook has the
  photodiode's first reading.

## 0.6.7 - Why zero is 5 mm off the stop

- The hardware notes explain the builder's finding that A/B zero sits
  about 5 mm from the hard stop: Marlin's homing bump (5 mm, then a slow
  second approach) with sensorless homing, where the slow approach most
  likely stalls at once. Possibly also the "back edge" past A/B 35. Not
  changed now, since it would move every coordinate mid-commissioning.

## 0.6.6 - The jog arrows move the stage

- The window's jog arrows (and `w a s d`) now move **the stage** the way
  they point, as the operator stands at the machine; they moved the spot
  over the sample, which goes the opposite way and felt backwards (the
  builder, 2026-10-28; D19 revised). The right arrow is now +A / +X, as
  the command line's `d` always was.
- The hardware notes say which way the stage itself moves (+A right, +B
  up, as the operator stands) and that earlier notes on "the sample"
  moving meant the spot.
- The photodiode's reach: it is on the side that comes to the beam as A
  rises. The CAD puts laser 1 about 12 mm lower in X than `machine.toml`
  does, which decides how much X travel is left; to check at the
  machine.

## 0.6.5 - The new stage's photodiode mount; the back contact

- The new stage's design, from the builder: the photodiode 35 mm from
  the AB centre along A, two scalpel blades crossing over its chip with
  the A+/B- quarter open, the B-parallel blade 0.4 mm lower and at the
  sample's height ([hardware](docs/hardware.md)). Whether lasers 1-3
  can reach it with AB centred depends on which side of the stage it
  is, still to confirm.
- The test cell's contact: its back contact loses pressure on the
  backplate when the stage moves (held only by Kapton at its edges),
  not just the clip leads. The bench runbook says to press it down.

## 0.6.4 - Step-and-measure and the sync check

Phase 6 step 2, in simulation.

- **`multilbic sync-check`**: in one session (one homing, one XY
  placement), step-and-measure over a patch with one edge, continuous
  rows over it at several speeds, and step-and-measure again. Every
  edge is fitted; against step-and-measure, forward and reverse rows at
  two speeds or more give the timing error `L` and the A backlash
  separately, which the serpentine alignment can't. Also the drift over
  the session, and the spot's width. `sync.json` holds the result; each
  pass is an ordinary run file. ([run](docs/run.md))
- **Step-and-measure** (`run/steps.py`): each point reached moving up
  along A, a settle, then the stream averaged over whole mains periods.
  Its run file has `mode: steps` and no row anchors.
- **Edge fits** (`scan/edges.py`): an error function with a leaning
  background, fitted by Levenberg-Marquardt in numpy; the edge in every
  row, refitted near the map's median edge so a noisy row can't wander.
  The same fit will serve the photodiode's knife-edge scans.
- **`multilbic edges`**: the edge in every row of a run file, the
  forward/reverse shift from the edges and the alignment's; or a sync
  check's result again from its folder.
- On the maps made so far, the edges agree with the alignment on broad
  spots and not on sharp ones (+19.9 against +9.4 um on the refocused
  laser 2), which settles the open finding as the alignment's
  ([hardware](docs/hardware.md#edge-fits-on-these-maps-2026-10-28)).
  Laser 3 fits 145 um wide against the 244 um in `machine.toml`.
- Simulator: an SMU that stamps packets late (`Faults.smu_stamp_lag_s`),
  a sample with one straight edge, and `open_sim(sample=)`. On it the
  check recovers an injected 18.6 ms stamp lag and 20 um backlash to
  1.5 ms and 3 um.
- Bench runbook for step 3 in [bench](docs/bench.md#phase-6-the-sync-check).

## 0.6.3 - Phase 6's plan after current ranges

- Step 5 picks channel 2's range with `run/ranges.py`'s choice, and
  reads each laser's power after its warm-up and the relight wait.
- Step 6 (focus assist) fits each pass with its own plateau, so power
  drift isn't read as focus, and alternates direction so the stamp lag
  cancels.
- Step 8 is the new stage the user is designing and printing: the
  photodiode, a blade, and soldered cell contacts. How the blade sits is
  still being agreed.
- D22 names the tab "Lasers", as the steps already did.

## 0.6.2 - Current ranges merged in

- main merged into Phase 6: current ranges per sample (PR #7,
  0.5.16-0.5.27). Phase 6 now has per-laser ranges checked at
  calibration, the step-up on a clip, 4 mm/s by default, and the laser
  driver's 3 s relight wait (laser 1 relit sooner comes back at 40 %).
- On the bench, nA on every laser means the test cell's crocodile clips
  have lost contact (homing can do it): reseat them
  ([hardware](docs/hardware.md#current-ranges-on-the-test-cell-2026-10-27)).

## 0.6.1 - 5 mm/s in step 3

- Step 3's bench session maps the test cell's edge at 5 mm/s too, to
  decide whether the default speed can move from 4 to 5 mm/s: the
  stream then runs at 1000 Hz and the serpentine shift is largest.
  (Asked for 2026-10-27, while the default moved from 2 to 4 mm/s on
  the current-ranges branch.)

## 0.6.0 - Phase 6 planned: commissioning

- Phase 6's plan in [plan](docs/plan.md#phase-6-commissioning), agreed
  2026-10-27: step-and-measure and per-row edge fits first, then a bench
  session that needs no photodiode (the sync error on the test cell's
  straight edge, the open alignment finding); then the photodiode in
  the simulator, `multilbic commission` and a Lasers tab to find each
  laser, measure its spot and help focus it (passes across the
  photodiode's edge, showing live whether a turn of the focus made the
  spot sharper); then mounting and the bench with all six lasers.
- D22: commissioning is both a command and a window tab. D24: focus
  stays a hand adjustment, with the photodiode as its gauge. D23: results
  go into `machine.toml`, shown first and written on the operator's
  yes.
- The Hamamatsu S1223-01 photodiode has arrived; not yet mounted.

## 0.5.27 - Two tests that raced on CI

Tests only.

- A run's fault test broke Marlin from a thread that re-read the whole
  data file every 20 ms; on a slow Windows runner that starved the
  simulated stream, and row 1 failed short of samples before Marlin's
  silence showed. The fault now lands from the run's own row callback,
  right after row 0.
- Two window tests pressed Start run before Run setup had made its
  plan, when Start is still disabled and the press does nothing (Ubuntu
  runner). They now wait for Start to be enabled.

## 0.5.26 - The clips, on record

No code changes.

- Rechecked on 0.5.25: laser 1 80 uA (650u), laser 2 0.31 uA (1u),
  laser 3 91.9 uA (650u); the relight wait fixed laser 1's under-read.
- The two checks that read nA on every laser were the cell's
  crocodile-clip contact, which homing can make or break (a stress
  test: five homings, five different levels; no motion, 20 switch-ons
  all alike). Not handled in software, since the final stage is
  soldered; docs/hardware.md says what to look for.

## 0.5.25 - A laser stays dark before it relights

- Laser 1 relit within about 1.5 s of going off comes back at 40 % of
  its power and stays there (bench, 2026-10-27; laser 3 doesn't). That,
  not warm-up or autorange, is why a check read it at 24 uA where runs
  read 90 uA. The laser driver now waits until a laser has been dark
  for `[laser_board] relight_ms` (3000, new and optional in
  machine.toml), counting the servo's settle, and selecting the laser
  already on sends nothing (the firmware would switch it off and on).
- Correction to 0.5.24: the miniSMU's autorange did not stick at the
  bench; it climbs within two readings. The re-read near a range's top
  stays as a safety net; its docs and log say so.

## 0.5.24 - A check stuck at a range's top reads again

- The miniSMU's autorange stayed on 25 uA for laser 1 on the test cell:
  the check read 24 uA where the map read 97 uA. Not warm-up: laser 1
  brightens only 10 % over the run's minute. A check whose brightest
  reading sits at 0.8-1.1 of a range's top now reads that laser's grid
  again with the next range up fixed (and the next while that clips),
  then goes back to autorange. The result records `autorange_top_a`;
  older files load without it.
- The simulator can pin autorange on a range (`autorange_stuck`), to
  test it.

## 0.5.23 - Ranges on the bench

Ranges step 6, on the test cell (2026-10-27): no code changes.

- Check ranges chose 650u, 25u, 650u for lasers 1-3, as expected; a
  three-laser run on them completed with no clip; laser 1 set to 25u
  by hand clipped on row 0, stepped up to 650u and completed.
- Results in docs/bench.md and docs/hardware.md. Open: laser 1 read 4x
  brighter after the run's warm-up than in the check, more than the 3x
  headroom.

## 0.5.22 - The range check logs each line

Ranges step 6, on the bench. The first check on the test cell found
1-12 nA peaks where a map of it reads 40-130 nA.

- Each laser comes on before the stage travels to its grid, not after,
  and stays on through all six lines. A no-motion test on the bench
  (2026-10-27) showed laser 2's light on the cell within 0.25 s of
  selecting it, then about 25 % brighter over the next 4 s; this gives
  it the travel time to warm.
- Each grid line goes to the log: where it ran, how many readings, and
  the lowest and highest. If a check reads too little again, the log
  shows which lines and where.
- Also found: single readings agree with the stream (-37 to -47 nA
  against -46 nA, laser 2, same spot), so the readings themselves are
  not the cause.

## 0.5.21 - The ranges line follows every laser ticked

- On the Pi, with lasers 1-3 ticked by a script rather than by clicks,
  Run setup's Ranges line still showed only laser 2: it was rebuilt
  only on a click. A laser missing from it would map with the default
  range without saying so. It is now rebuilt whenever the ticked lasers
  differ from what it shows. The column with the new rows fits the
  Pi's window, with about 60 px to spare.

## 0.5.20 - Ranges in the window

Ranges step 5.

- Calibration's step 4, **Check ranges**: for the lasers ticked in Run
  setup, at its bias; asks first with the time it takes; the result
  beside the button.
- Run setup: **Ranges**, a range per ticked laser, two to a line, each
  saying "checked", "set by hand" or "guess"; "Range if not checked"
  fills the guesses; **step up if clipped** (on). A check replaces
  guesses and older checks, never a range set by hand.
- **Start run** with a guessed range offers the check first (Yes /
  start anyway / Cancel).
- The Plan tab's table gives each laser's range and where it came
  from; a note says when any is a guess, and what a clip will do.
- The calibration drawing is 150 px tall (was 220), so the column with
  its new rows still fits the Pi's window.
- Tests: every dialog in the window tests now fails the test unless
  the test answers it. The new Start question had popped up for real on
  the developer's screen and waited (2026-10-27). The test of closing
  the window mid-run waits for the run to begin before closing; on a
  busy machine it had closed it a moment before, which stops a run
  before it makes its folder (correct, but not what the test checks).

## 0.5.19 - Ranges checked at calibration

Ranges step 4 (D25).

- `Calibrator.check_ranges(lasers, bias)`: for each laser, XY places the
  sample as a run will for it, the laser comes on, and the stage runs a
  coarse grid over the sample (3 lines along A and 3 along B, at 1/6,
  1/2 and 5/6, at 2 mm/s) while single readings are taken on autorange
  at the run's bias. The range is the smallest holding 3x the brightest
  reading (`multilbic/run/ranges.py`); a reading at the check's own
  1 mA limit is flagged and gets at least 15 mA. It ends with the
  reference laser back on the corner; `halt()` stops it, keeping
  nothing half-checked.
- Saved in the calibration file (`current_ranges`: per laser the range,
  the brightest reading, the bias, when); older files load without.
- `calibrate`'s `ranges 1,2,3 [bias]`; the window's worker gets
  `check_ranges` (its button comes in step 5), and its calibration
  events carry the ranges.
- **`run` without `--current-range` uses the ranges checked for the
  sample**, 25 uA for a laser not checked, and says which; with
  `--current-range` it uses that as written.
- `Calibrator` (and the prompt) take the clock, as the run code does.
- Tested in simulation: 25 uA for the synthetic cell, 650 uA for one a
  hundred times brighter, the corner reached again, halt, the round
  trip through the file, the prompt, the worker, and `run` picking the
  checked range up or being overridden.

## 0.5.18 - A clipped laser starts again one range up

Ranges step 3 (D26).

- A range that clips no longer ends the run. The clip is its own fault
  (`RangeClipped`); the laser stops as for any fault, its attempt is kept
  as `laserN_<nm>nm_<range>.csv` with the status `clipped`, and its
  whole map starts again one range up, with a fresh baseline and no
  second warm-up. A `laser_step_up` event, the final file's header and
  `run.json` (each laser's final range and clipped attempts) record it.
  At 180 mA there is no range left, and the run fails as before.
- On by default; `run --no-step-up` (and `RunRequest.step_up`) turns it
  off. The window's box comes in step 5.
- The live map and the progress start that laser again too, so rows
  from the two ranges never mix; the run column says the range clipped.
- Tested on the synthetic cell twice as bright: at 1 uA, laser 2 clips,
  starts again at 25 uA and completes with every row.

## 0.5.17 - A current range per laser; all five ranges

Ranges step 2.

- A run maps each laser with its own range: `RunRequest.laser_ranges_a`
  (`range_for(laser)`), and `run --current-range` takes one range for
  all, one per laser (`1=650u,2=25u,3=650u`) or both (`25u,1=650u`).
  The command line prints each laser's range. Each laser's file header
  and `run.json` record the range it used; a range given for a laser
  not in the run is refused before anything moves.
- **180 mA**, the miniSMU's top range, is offered (the list stopped at
  15 mA, though `docs/hardware.md` and the driver have five).
- **The SMU's current limit follows the range**, at its full scale; it
  was always 1 mA, which made 15 mA and 180 mA unusable. Autoranging
  keeps 1 mA. Recorded in each file header as `current_limit_a`. The
  real SMU has not yet been given a limit as low as 1 uA or 25 uA:
  checked at the bench step.
- The window's run form carries ranges per laser already; its controls
  come in step 5.

## 0.5.16 - Current ranges per sample planned; 4 mm/s by default

- The plan for current ranges per laser and per sample, agreed
  2026-10-27 (`docs/plan.md`, "Current ranges per sample"): ranges
  checked at calibration on a coarse grid and saved with it, a range per
  laser in Run setup, Start offering the check, a clipped laser starting
  again one range up, all five of the miniSMU's ranges with the current
  limit following the range. D15 revised; D25-D27.
- **The default scan speed is 4 mm/s** (was 2), in the window and
  `multilbic run` (D27): the bench maps at 4 mm/s were good, and runs
  are about 40 % shorter. 5 mm/s is checked in Phase 6 step 3.

## 0.5.15 - The Plan tab fits any number of lasers; the right version

- On the Pi the Plan tab's notes were cut off at the bottom (reported
  by the user, reproduced with all six lasers: 83 px short). The tab is
  now laid out from the bottom up, so the drawing gives up height and
  the text never does; the close-ups share the tab's width (six fit);
  the pitch is said once beside them; lasers without a measured spot
  share one note. Checked on the Pi with three and six lasers. (The
  first of these changes went out in a commit titled "wip", by
  mistake.)
- **The version shown and recorded was the installed one, not the
  running one.** `importlib.metadata` gives the version recorded at the
  last install, and `uv run --no-sync` skips installing: the window on
  the development PC said 0.5.3 while running 0.5.14, and run files
  (`run.json`, events, file headers, bench reports) would carry the
  same stale number after a `git pull` on the Pi. `multilbic.version`
  now reads `pyproject.toml` beside the package, falling back to the
  installed record only without a checkout. Run files written by
  0.5.x on the Pi were right, since `setup.sh` installs each time.

## 0.5.14 - Fits the Pi's fonts

- Checked on the Pi's screen (2026-10-27): the Plan tab and everything
  else fit 1920 x 1080 with the Pi's fonts, except the corner's
  coordinates and the run setup's summary line, which ran a few
  characters past their panel. The corner now takes two short lines;
  the summary wraps sooner.
- Start (calibration) says in the footer that the laser is on, instead
  of leaving "homing" there.

## 0.5.13 - The Plan tab; a fuller time estimate

Asked for after the bench session, on the same branch.

- **The Plan tab**, the run column's first: the run as set up, drawn and
  timed, following the fields as they are typed. The sweep as the
  operator sees the stage (rows and their direction, run-up and run-out,
  where it starts, the spot at true scale); a true-scale close-up per
  laser of its spot on a few rows and the pixels; each laser's time and
  the clock time it would be done by; plain-word notes on pitch, pixel,
  speed and spot (`multilbic/gui/plan_view.py`).
- **Spot sizes** in `machine.toml`: an optional `spot_um` per laser,
  the 10-90 % width of an edge through the spot. Lasers 1-3 from the
  bench of 2026-10-23 (65, 41, 244 um); 4-6 wait for the photodiode.
- **A fuller estimate** (`estimate_run`, for the window and `multilbic
  run`): homing, XY travel from the distances between placements, per
  laser the fixed cost, baseline, warm-up, rows and the map's building
  time from its samples; everything that depends on the sample is
  computed from it. The per-row overhead is now 0.13 s (was 0.02), as
  measured. On the step 9 run: 3 min 43 s estimated, 3 min 41 s taken
  (it said "3 min, plus homing" before). Each run records its estimate
  in `run.json`.
- Run setup: each field's unit is in its label. On the Pi the units
  were in a dim colour at the panel's edge and easy to miss.

## 0.5.12 - A window test that waited for the wrong plan

- `test_a_bad_field_blocks_start` failed on the ARM CI runner: the run
  setup re-plans 150 ms after a change, and the test's wait for "no
  plan" after typing a bad pitch was already met by the earlier "no
  calibration yet" plan when the runner was slow. It now waits for the
  calibration's plan first, then for the pitch's message. The window
  itself was right.

## 0.5.11 - A map from the window; Phase 5 done

Phase 5 step 9, on the machine (2026-10-26 and 27; `docs/bench.md`,
findings in `docs/hardware.md`):

- The window connected to the real devices and held the machine lock;
  calibrated (Start, Load, Go to corner, jog, Trace, Save); ran a full
  map of the cell's right edge with laser 2 at 1 mm/s; and STOP, Esc
  and closing the window each stopped a run mid-row, keeping every
  finished row, with the lock released on closing.
- Row timing matched the command line's to 0.2 ms: the window's
  redraws delay nothing. The shift measured from the edge (+23 um)
  agrees with 2026-10-23's; the edge itself sits 0.2 mm further in and
  is much sharper, after laser 2 was refocused by eye in between.
- Found: the map's alignment reported +9.4 um on this sharp-spot map,
  against +23 um from the edge. Left open in the plan.
- The runbook's homing check used a calibration whose corner is not a
  feature; noted in `docs/bench.md`.
- Phase 5 is done.

## 0.5.10 - The window's docs; the bench session planned

Phase 5 step 8.

- `docs/gui.md`: how it runs on the Pi (D21), and a map of the window's
  modules and what they stand on. `docs/development.md`: running the
  window in simulation, and how the window tests work (one Tk per
  module, the worker closed in `finally`, focus before keys, the thread
  guard, running them on the Pi's display from SSH).
  `docs/architecture.md`, `docs/run.md`, `README.md`: the window as
  built.
- `docs/bench.md`, "Phase 5: a map from the window": step 9's runbook.
  The real machine from the window on the cell's straight right edge
  (`stdtest-redge`), compared with the command line's maps of it; the
  machine lock; jog arrows on the real cell; STOP, Esc and closing the
  window mid-run.

## 0.5.9 - The emblem's lasers in order

- The emblem's dots ran 1-2-3-6-5-4 round the ring (the user spotted
  it); they now run 1 to 6 clockwise, each laser opposite the one it
  shares a servo angle with. A test checks both.

## 0.5.8 - Colour: laser wavelengths and accents

- Each laser is shown in roughly the colour of its wavelength, as the
  old script showed them (`multilbic/gui/spectrum.py`): blue, green,
  red, a deeper red, then dark maroons into the infrared, ringed in grey
  on the dark theme. A dot on its button, which fills with that colour
  while the laser is on (the text black or white, whichever reads); its
  box in Run setup, now two rows of three like the revolver; its map
  tab; the spot in the calibration drawing.
- SMUniversal's header accents: the accent bar (down the left in dark,
  under the strip in light), a subtitle, and an emblem of MultiLBIC's
  own, the laser revolver with a dot per laser.
- The calibration drawing is 220 px tall (was 300), so the sample column
  fits 1080 px in the light theme too.

## 0.5.7 - The window passes on the Pi

- Phase 5 step 7 passed (2026-10-26): on deadsnakes' Python 3.14.9 with
  Ubuntu's Tk 8.6 the Pi's text is smooth, the simulated window works
  as before, all 239 tests pass over SSH and the 15 window tests on the
  Pi's display.

## 0.5.6 - Smooth text on the Pi

Phase 5 step 7, on the Pi (2026-10-26): the simulated window fitted
the Pi's screen, every step of the checklist worked (`docs/bench.md`,
"Phase 5: the window on the Pi"), and the window tests passed on its
desktop. But the text was jagged.

- Why: uv's Python 3.14 for aarch64 has a Tk 9.0 built without Xft
  (`::tk::pkgconfig get fontsystem` is `x11`), so Tk can only draw the
  old X bitmap fonts. Ubuntu's own Tk 8.6 is built with Xft.
- D21: the Pi uses the deadsnakes PPA's `python3.14` with
  `python3.14-tk` (Ubuntu's Tk). `deploy/pi/setup.sh` prefers
  `/usr/bin/python3.14` when it has tkinter, makes `.venv` again if it
  came from another Python, falls back to uv's with a warning and the
  commands to fix it, and reports whether the fonts will be smooth.
- `deploy/pi/README.md` installs that Python; the docs that said the Pi
  runs a uv-managed 3.14 say why it no longer does.

## 0.5.5 - Live and finished maps in the window

Phase 5 step 6 (`docs/gui.md`).

- The run column: what the run is doing, a progress bar, time so far
  and left (the estimate until three rows are done, then their pace),
  and a tab per laser. The live map bins each row as it finishes,
  baseline subtracted and mains removed but not corrected for the
  serpentine shift (D18); the finished map, built from the file as the
  PNG is, replaces it when the laser ends, with the shift it found.
  Open run file... draws an earlier run's map; Open folder.
- `multilbic/gui/livemap.py` (no Tk): `LiveMap` bins straight into a
  grid of at most 600 pixels a side, so a redraw of a 30 x 30 mm map at
  10 um costs 74 ms here instead of 243 ms, and holds no 9-million-pixel
  arrays; `RunProgress` for the time left.
- The live map removes mains on the SMU's timestamps, as the finished
  map does: on the host's arrival times, which come in ~100 ms bursts,
  the fit wrecked the map (caught by a test comparing the two maps of
  one simulated run).
- `multilbic/store/image.py`: `draw_map`, shared by the PNG and the
  window. The "corner" label now sits on the map's side of the corner
  whichever way the view turns it, instead of over the colour bar.
- The laser a run lights is shown filled in the Lasers panel. Ticked
  boxes stay visibly ticked while a run locks the form (SMUniversal's
  theme drew them empty; overridden here).

## 0.5.4 - Calibrating and starting runs from the window

Phase 5 step 5 (`docs/gui.md`).

- Calibration panel: the sample's name, then `calibrate` as three steps
  (Start, Set corner here; width and height; Trace the outline), with
  Save, Load and Go to corner. A drawing shows AB's safe range, then
  zooms to the sample as a run places it, with the corner, the spot as
  it moves (red while a laser is on) and a scale bar, turned as the
  operator sees the stage.
- Run setup: `multilbic run`'s options with its defaults, checked as you
  type with the checks `run` makes before anything moves; the problem
  shows in red and Start stays off. Warnings above 5 mm/s (D9) and for
  autoranging (D15). Start run shows the plan and asks (D20), then the
  window runs it; everything but STOP is off until it ends.
- `multilbic/gui/runform.py` (no Tk): the typed fields to a request,
  plans, estimate and summary, or the field that is wrong.
- The worker's calibration events carry the calibration; save takes
  the sample name; it logs the corner, the size and the end of a trace.
- `CURRENT_RANGES` and the default run folders moved from the command
  line to `multilbic.run.session`, for the window to share.

## 0.5.3 - The window: machine column

Phase 5 step 4. `multilbic gui [--sim]` (`docs/gui.md`).

- The window: header with STOP (and Esc anywhere), Light/Dark, Console;
  the machine column (connection lamps and firmware, Home, Centre AB,
  Motors off, position, the jog pad, go to, the six lasers and Off, the
  live photocurrent); a footer with the last thing that happened. The
  sample and run columns are placeholders until steps 5 and 6.
- Jog arrows move the spot on the sample the way they point as seen at
  the machine, worked out from `[display]` and `[geometry]`: on this
  machine ← is +A or +X, ↓ is +B or +Y. Keys only while the pad has the
  keyboard (D19). In the window `w a s d` follow the arrows, unlike the
  command line's key mode, where `d` is X+.
- The worker refuses moves until the stage is homed, and again after
  Motors off; it logs laser changes.
- Closing during a run asks, then stops it and waits until everything
  is safe.
- SMUniversal's theme with a MultiLBIC accent (teal), its console
  window, and its Tk thread guard in the window tests: no worker thread
  touched a Tk variable.
- Window tests against the simulator (CI runs them under xvfb, as it
  already did for Tk). They share one Tk: starting Tcl afresh for every
  test failed now and then on Windows.

## 0.5.2 - The machine behind the window

Phase 5 step 3, no Tk yet.

- `multilbic/gui/worker.py`: `MachineWorker`, one thread that owns the
  devices. The window calls it (connect, home, start calibration, jog,
  move, centre, laser, here, size, trace, save, load, start a run,
  Stop) and reads its events (state, log, position, photocurrent,
  laser, calibration and outline, each row, each map, run end). One
  action at a time: anything sent while the machine is busy is
  refused, as key mode drops keys. Stop acts at once: a run stops as
  Ctrl+C stops it, a calibration move halts with the laser left on,
  and Stop while idle turns the laser off. While idle and homed the
  photocurrent is read twice a second.
- `multilbic/run/devices.py`: opening the machine, shared by the
  command line and the GUI. The real machine is opened only under the
  **machine lock** (the OS's file lock, SMUniversal's `SingleInstance`,
  in MultiLBIC's own file), so `calibrate`, `run` and the GUI can't
  drive the ports at once (D17); the OS drops it when the process ends.
  `open_sim` builds the simulated one.
- Tested against the simulator: calibration, refusal while busy, Stop
  during a trace, a run, Stop mid-run, Stop in the instant before a run
  starts, an SMU stall mid-run, closing during a run, a failed
  connection, the unchecked-directions refusal, the lock.

## 0.5.1 - Calibration and runs ready for a window

Phase 5 step 2. The command line works as before.

- `Calibrator` (`multilbic/run/calibrate.py`) does calibration's
  actions and returns what it found: start, jog, move, centre, laser,
  read, here, size, trace, save, plus `adopt` (a saved calibration's
  corner and size) and `outline_ab` (the outline a trace runs, for a
  preview). `CalibrationPrompt` is now the text layer on top of it.
- `Calibrator.halt()`, from any thread, stops the move in progress: a
  trace or a placing move of several steps stops there and raises
  `RunStopped` instead of carrying on. The laser stays as it was.
- `approach()` takes a `stop` event and checks it before every move;
  runs pass theirs, so Stop during XY placement no longer lets the
  next move of the placement go out.
- `Session(on_row=..., on_map=...)`: each block of samples (baseline,
  warm-up, every row) once it is on disk, and each laser's finished
  map. A hook that raises is reported once and left out; it never ends
  the run.
- `RunStopped` lives in `multilbic.run.motion` now (still importable
  from `multilbic.run.rows`).

## 0.5.0 - Phase 5 planned

- The GUI's plan is agreed and in `docs/plan.md`: a worker thread that
  owns the devices behind queues, the window's three columns, nine
  steps, and when the Pi is needed (once with the simulator on its
  monitor, then the bench). D6 is decided (the GUI is not reached
  remotely) and D17–D20 are new: the run lives in the window, the live
  map is uncorrected until each laser ends, jog keys work only while
  the jog panel has focus, and Start asks to confirm. No code yet.

## 0.4.13 - Saturation test without a servo turn

- The saturation test is back on laser 2 with a cell twice as bright:
  laser 3's servo turn, at 20x simulated speed, left the board's reply
  about 0.15 s of real time, which the Pi missed once (2026-10-26).

## 0.4.12 - Command-line test with a short warm-up

- On the Pi, `test_run_sim_end_to_end` failed with a stalled stream
  after 0.4.11's default 60 s warm-up: at 20x simulated speed the
  24,000 warm-up samples took longer to sort on the Pi than the 0.1 s
  real (2 s simulated) the stream check allows. On the machine the same
  work fits easily. The test now passes `--warmup 1`; the warm-up is
  tested in `test_session.py`.

## 0.4.11 - Laser warm-up; Phase 4 done

- `multilbic run --warmup` (default 60 s): each laser stays on with the
  stage still before its first row. Laser 2's output rose about 2x over
  the two minutes after it was switched on (bench, 2026-10-23). The
  warm-up samples are kept in the run file as row −2, so the settling
  can be checked; maps ignore them. Stop works during the warm-up.
- Step 7 on the bench: lasers 1, 2 and 3 on the cell's straight right
  edge. Lasers 1 and 3 give 60-80 uA and need the 650 uA range; laser 2
  gives 0.7 uA. Spots after refocusing by eye: 65, 41 and 244 um
  (10-90 %). Registered to within about 0.3 mm on today's
  `xy_centre_mm`; the photodiode corrects them in Phase 6. Findings in
  `docs/hardware.md`; decisions D15 (fixed range) and D16 (warm-up) in
  the plan.
- Phase 4 is done: real maps from the command line, without the GUI.

## 0.4.10 - Alignment that works with a real spot

- On the bench the serpentine alignment found nothing, even with a
  sharp edge crossing every row: it smoothed rows over 2 um, right for
  the simulator's 5 um spot but pure noise against laser 2's ~0.2 mm
  spot. It now tries smoothing widths from 2 to 80 um, finest first,
  and keeps the first that a clear majority of row pairs (at least half,
  at least 3) trust and agree on (spread within the smoothing plus
  20 um). On the bench runs it now finds +19.6 um at 1 mm/s and
  +138.7 um at 4 mm/s, against +20.5 and +131.9 um from fitting the edge
  row by row, and still reports "not found" on rows of pure noise.
  The search reaches 0.4 mm (was 0.2), and shortens on short rows.
- The smoothing used is recorded with the shift.
- `docs/hardware.md`: findings from the first maps (box, lead, signal,
  spot, the shift and its 18.6 ms stamp lag, the cell, Stop).

## 0.4.9 - Maps drawn as the operator sees the cell

- Bench, 2026-10-23: watched with the box off, a scan starts at the
  sample's top-right corner, runs each row leftwards (+A) and steps the
  rows downwards (+B). The PNGs were drawn with u to the right and v up,
  turned 180 degrees from that. `machine.toml` gains `[display]`
  (`u_points = "left"`, `v_points = "down"`), and maps are now drawn
  that way, at true scale, with the calibration corner marked.
- `multilbic map RUNFILE` rebuilds a map from its run file alone and
  draws it again, e.g. for runs made before this change.
- `docs/hardware.md`: the orientation note now says what the bench
  showed; the step 1 pairing (X with A, Y with B) is unchanged.

## 0.4.8 - The saturation test no longer depends on noise

- `test_a_saturated_range_stops_the_run` used laser 2, under which the
  synthetic cell gives 0.87 uA: it only reached the 0.98 uA threshold
  when simulated noise pushed it there, so it passed on Windows and
  failed on the Pi. It now uses laser 3, where the cell gives the full
  1 uA and clips every time. The check itself is unchanged.

## 0.4.7 - The channel-2 photodiode is chosen

- `docs/hardware.md` records the reference photodiode for channel 2:
  Hamamatsu S1223-01 (RS 415-5722), with the Vishay BPW34 as a cheap
  fallback, the photodiode types to avoid, and how to mount it and pick
  its range. Not bought yet.
- The miniSMU's envelope is now in `docs/hardware.md` too: ±12 V,
  ±180 mA, five current ranges up to 180 mA, and 50 mA per channel on
  USB power alone.

## 0.4.6 - Scans use a fixed current range

- First real maps (bench, 2026-10-21): with laser 2 on the cell the
  photocurrent sat at 0.6-2.1 uA, across the miniSMU's 1 uA / 25 uA
  boundary. Autoranging dropped 10-15 ms of samples at every crossing,
  the stream fell to ~200 Hz, and the run stopped itself after 12 rows
  (the under-delivery check, as designed: motion stopped, laser and SMU
  off, rows kept). Findings in `docs/hardware.md`.
- `multilbic run --current-range` (`1u`, `25u`, `650u`, `15m`, `auto`;
  default `25u`) fixes the measurement range with autoranging off
  (`PhotocurrentSmu.prepare(current_range_a=...)`). A baseline or row
  that reaches the end of the range stops the run: clipped data is wrong,
  not just noisy. The range goes into every file header.
- The fake SMU clips at a fixed range, and gains
  `set_current_range_by_limit` like the library.

## 0.4.5 - Axis directions checked on the machine

- Bench step 1 (2026-10-21, laser 2 on a mark): +X and +A move the
  sample up, +Y and +B move it right, as the operator sees it; both
  stages home to the bottom-left. `machine.toml` keeps `x_along = "+A"`,
  `y_along = "+B"` and now says `directions_measured = true`, so `run`
  accepts the machine.
- That makes the calibration corner the sample's **top-right** corner
  as seen at the machine. The calibrate prompt and the docs now say so.

## 0.4.4 - setup.sh runs the steps it just checked out

- The run of `deploy/pi/setup.sh` that fetched 0.4.3 still failed the
  three timing tests: `git checkout` replaces the script with a new file,
  and bash goes on reading the old one it had open, so the rest of that
  run was the previous version's. After checking out, the script now
  starts again from the fresh copy (once).

## 0.4.3 - Simulator timing tests skipped on the Pi

- `deploy/pi/setup.sh` on the Pi failed three tests that check the
  simulator's timing to about a millisecond (`test_sim_scan.py`, and the
  two-laser test in `test_session.py`): sample times off by 4-8 ms.
  `ScaledClock(precise=True)` spin-waits in several threads, and on the
  Pi's slower cores they contend for Python's GIL and delay the readers.
  Real runs use the real clock and never spin, so this says nothing
  about the machine. These tests are now marked `sim_timing` and
  skipped by `setup.sh`; CI, including its ARM runner, still runs them.

## 0.4.2 - Ready for room light

The room light can't be fully turned off for the first maps.

- The lowest stream rate is now 400 Hz (was 200). Room light flickers
  at 100 Hz; at 200 Hz that flicker, and the 150 Hz mains harmonic, sit
  at or near half the sample rate, where the per-row cleaning can't fit
  them. A 10 µm pixel at 1 mm/s now streams at 400 Hz.
- `multilbic run --note "..."` writes free text (lighting, contacts)
  into every file header and `run.json`.

## 0.4.1 - Jog with keys during calibration

- `keys` in `multilbic calibrate`: `wasd` jogs (`d`/`a` X or A,
  `w`/`s` Y or B), `q` switches XY/AB, `e` cycles the step 0.1, 1, 10 mm;
  Esc, Enter or Ctrl+C go back to typed commands. Keys pressed during a
  move are dropped, so a held key can't queue moves. Arrow keys are
  ignored rather than read as Esc.
- `multilbic/run/keys.py`: single key presses through `msvcrt` on
  Windows and cbreak mode elsewhere (the Pi, SSH), terminal restored on
  the way out. Tested with scripted keys, and through a pseudo-terminal
  on Linux CI.

## 0.4.0 - Phase 4: calibrate and run from the command line

Built and tested against the simulated machine; the bench session is
owed (`docs/bench.md`, "Phase 4: first maps").

- **`multilbic calibrate`** (`multilbic/run/calibrate.py`): homes, puts
  the reference laser over the AB centre, and gives a prompt to jog XY
  and AB, light lasers, read the photocurrent, record the corner, give
  the size, trace the outline with the laser, and save a calibration
  file. `--check FILE` puts a saved corner back under the beam.
- **`multilbic run`** (`multilbic/run/session.py`): checks everything
  before moving (lasers exist and are measured, XY reach, AB safe range,
  pixel against speed), homes, then per laser: XY under it, baseline,
  rows, run file, PNG. One folder per run with `run.json`,
  `calibration.json`, `events.jsonl` (SMUniversal's EventLog) and a file
  and map per laser. Runs on a worker thread; Ctrl+C, SIGINT or SIGTERM
  is Stop. `--sim` for either command.
- **XY placement** (D11, `scan/geometry.py`): calibration in XY under
  the reference laser; each laser's XY centres the sample on AB.
  `machine.toml` gains `[geometry]`: reference laser, which AB axis X
  and Y move along (`x_along`, `y_along`, not yet measured, so `run`
  refuses the machine until the bench checks them), take-up distances,
  and `ab_backlash_mm` (0 until measured).
- **Every placing move ends moving up** (`run/motion.py`), so backlash
  is always taken up the same way: calibration jogs, XY under each
  laser, AB to the first row.
- **Stop and faults** (`run/rows.py`): Stop is checked before every row
  and after every wait, and stops motion at once; a row in progress is
  not written. Marlin timeouts and halts, a silent laser board, and a
  stream that stalls, errors or under-delivers end the run the same way.
  However it ends: motion stopped, laser off, SMU off, file marked
  `complete`, `stopped` or `failed: <why>`.
- **Maps agree with calibration**: aligned maps are shifted by half the
  known A/B backlash, since calibration reads AB after moving up.
- **Simulator**: the rig is XY-aware (true sample position on the
  carriage, true axis directions and laser positions, 0.1 mm XY
  backlash), can produce the calibration a perfect operator would
  record, and the fake SMU can stall. `python -m multilbic.sim.scan` now
  goes through the same session as a real run.
- Tests: XY geometry for all eight axis arrangements; scripted
  calibration; two lasers lining up with swapped and reversed axes;
  Stop mid-run; the three faults; refusals; the command line end to
  end. The suite takes ~65 s.
- Docs: [run](docs/run.md) is new; bench, plan (D11–D14), architecture,
  README and development updated.

## 0.2.2 - Fake Marlin stops motors and stage at one instant

- Ubuntu CI failed `test_quickstop_interrupts_a_wait` after Phase 3
  merged: `M114` reported 3.7795 mm, the stage 3.7810. The fake's
  quickstop (changed in 0.2.0 for backlash) read the clock once for
  the motor position and again for the stage's, so a thread stalled
  between the two put them 0.75 ms of motion apart. It now reads the
  clock once. `test_quickstop_stops_motors_and_stage_at_one_instant`
  reproduces it every time with a clock that moves on at each read.
  Simulator only; the drivers were not affected.

## 0.2.1 - Scan test: check sample times, not the drift's sign

- Ubuntu CI failed `test_clock_map_follows_the_drift`: the fitted drift
  came out +20 ppm against the injected -100. Over the ~20 s simulated
  scan, 100 ppm is only 2 ms, about the scatter a busy runner puts on
  the clock map's window minima, so the slope is not resolvable there.
  The test now checks what drift would spoil: every sample's mapped
  time is within 5 ms of its true time (5 µm at 1 mm/s, the edge
  tolerance). Drift recovery stays tested on a 60 s synthetic stream
  in `tests/test_scan_timing.py`.

## 0.2.0 - Phase 3: the scan core, in simulation

A new session, so the second number moves. The first push of this
work was labelled 0.1.12 by mistake; it is the same change.

- **The scan core** (`multilbic/scan/`, no I/O): sample frame, row plan
  (serpentine, run-up from the acceleration, stream rate from the pixel
  size, bounds and speed refused before anything moves, time estimate),
  the scan's own trapezoid model, the clock map (lower edge of each
  window's smallest arrival gap, updated as samples arrive), row anchors
  on the `M400` ok, the serpentine shift from cross-correlating
  neighbouring rows, dark baseline, per-row mains removal, the pixel
  grid, and `build_map()` from a run's raw record. Slow drift is left
  in (D8, set aside: no enclosure for now).
- **The run file** (`multilbic/store/runfile.py`): one CSV per laser
  map, `#` header, `#row` anchors, one line per packet with both
  timestamps, appended and flushed per row, a trailer at the end
  (status, clock map). Reader included. Maps save as PNG.
- **One laser's map on the devices** (`multilbic/run/rows.py`): position
  with B taken up from below, baseline with the laser off, laser on,
  rows; however it ends, laser off, stream stopped, output off and the
  file marked. Only run in simulation so far.
- **Simulators:** backlash per axis in the fake Marlin (a dead band
  between motor and stage) and the stage's whole path kept for
  checking; `M400` answers the moment the queue ends; reply latency and
  jitter on the fake link; bench-shaped noise in the fake SMU (mains,
  0.2–0.7 Hz drift) and delivery in 100 ms bursts; a synthetic sample
  with exact Gaussian-spot edges; `sim/rig.py` joins it all up.
- `python -m multilbic.sim.scan`: a headless scan of the synthetic
  sample with the agreed faults (5 ms latency, 20 µm backlash, SMU clock
  100 ppm fast). At 2× real time: worst A edge 3.8 µm (tolerance 5),
  worst B edge 9.4 µm (pitch 50), shift 9.93 µm measured vs 9.68
  present (tolerance 2), every on-sample position within 0.52 µm of the
  true stage. `tests/test_sim_scan.py` asserts these.
- Marlin replies carry `sent_s` and `received_s`; `wait_idle()` returns
  its reply.
- `ScaledClock(precise=True)`: sleeps short and yields to the exact
  moment. A plain sleep overshoots ~0.5 ms on Windows, which the
  speed-up turns into simulated latency the scan tests would measure.
- `machine.toml` gains `mains_hz = 50.0`. numpy and matplotlib are
  direct dependencies (already installed through SMUniversal).
- Docs: [scan](docs/scan.md) is new; architecture notes where the build
  differs from the design (end-only anchors, the file's trailer and
  channel column, mains by fitted sines).
- The suite takes ~37 s instead of ~22 s, mostly the end-to-end scan.

## 0.1.11 - Simulators slowed for busy CI runners

- Windows CI failed `test_jog_before_homing` with a spurious
  `MarlinTimeout`. At 100× simulated speed a 5 s timeout lasts only
  50 ms of real time, and a contended runner stalled the fake Marlin's
  thread for longer than that. Device tests now run at 20×, and the
  probes' and device check's simulations at 20× instead of 50×: a 5 s
  timeout is 250 ms real, and timing tolerances are 5× more forgiving of
  scheduling jitter. The suite takes ~22 s instead of ~9 s.

## 0.1.10 - USB boot check for the laser Xiao

- `deploy/pi/usb-check.sh`, with `multilbic-usb-check.service` and
  `install-usb-check.sh`: at every boot, if the laser Xiao has not
  appeared on USB within 15 s, the Pi's USB power is switched off and on
  with `uhubctl` (a software replug), then checked again. Every boot is
  logged (`journalctl -t multilbic-usb-check`). `--force` cycles even
  when the Xiao is present, as a test.
- `tests/test_deploy.py` runs the real script on Linux against a fake
  by-id folder and a fake `uhubctl`: present, recovered, still missing,
  forced.
- Installed on the Pi and verified with a forced cycle: every USB
  device dropped and the Xiao was back 7 s later.
- Findings: the miniSMU was simply switched off; the Xiao failure is
  intermittent, not tied to reboots or power order so far. 0.3 V leaks
  onto its 3V3 from the servo/laser supply. Recorded in
  `docs/hardware.md`.

## 0.1.9 - Speed trials on either axis

- `python -m multilbic.bench.marlin --speeds ... --speed-axis b` runs the
  speed trials on B. Only that axis moves.
- `--speeds` now needs only `--home`, not the full motion run, and each
  trial starts from a fixed position, so every timed move is a full
  20 mm.
- B speed trial on the bench: the same timings as A at 3–6 mm/s and no
  missed steps, but 6 mm/s was noisier with more vibration. The plan
  notes scans should use 5 mm/s or less (D9).

## 0.1.8 - Lasers checked; settle time from machine.toml

- Lasers checked on the bench:
  - each of the six lights alone, the right colour, at the right servo
    angle, so this Xiao drives them;
  - the "two at once" seen in the fast probe never showed up one at a
    time;
  - servo settle on the worst 120° swing is stable at 1000 ms and slides
    at 500 ms.
- Decision D10: the settle stays **2000 ms**, now in `machine.toml`
  (`[laser_board] settle_ms`, validated to the firmware's 0–10000 ms).
  `LaserBoard.open()` applies it whenever the board reports something
  else, because the firmware forgets a runtime value on power-up. The
  fake laser board records what it receives; tests cover both cases.

## 0.1.7 - A/B ceiling raised to 6 mm/s

- `machine.toml`: A/B `max_feed_mm_s` is 6.0 (decision D9). It matches
  the board's EEPROM, and A ran smoothly at 3–6 mm/s. A and B share it,
  being mechanically identical.
- The Marlin probe's stop test runs at a fixed 2 mm/s, so its results
  stay comparable whatever the ceiling. Tests updated for the new
  ceiling.

## 0.1.6 - Motion measured; no moves lost after a stop

- First homing and motion run on the machine:
  - homing takes 33.5 s;
  - A/B speeds are exact at 1 and 2 mm/s;
  - each move carries 113–135 ms, which is Marlin's 100 ms first-move
    delay plus acceleration;
  - Stop acts at once.
- Found on it: for 1 s after `M410`, Marlin silently drops new moves and
  reports their target as the position. `Marlin.quickstop()` now makes
  the next move wait with `M400` first. The fake Marlin models the
  lockout and keeps its reported and planned positions apart; two tests
  cover it.

- Speed trials on A at 3, 4, 5 and 6 mm/s: every speed was reached
  (model plus 0.1 s), and by eye and ear all were smooth. B was not
  tested above 2 mm/s. The motion run repeated within a few ms.

## Earlier on 0.1.5

- Contacted-cell noise measured:
  - lights on: −165 µA background, 1.7 µA RMS, mostly slow drift plus
    100 Hz flicker;
  - lights off and covered: −0.83 µA, 0.12 µA RMS, 81 % slow drift at
    0.2–0.7 Hz, 17 % at 50 Hz.
- The drift shares its band with map features, so open decision D8
  (enclosure and baselines, or laser chopping with a software lock-in)
  is added to the plan.
- The Xiao and the miniSMU needed a replug after every Pi boot. Recorded
  under "USB at boot" in `docs/hardware.md`.

## 0.1.5 - Bulk stream reader for the miniSMU

- `SmuStream` reads the miniSMU's serial port itself: everything waiting
  in one call, split into packets by `parse_packet()`. The library's
  per-line `readline()` read one byte per system call and fell behind
  the stream on the Pi; a bulk read kept up at 1190 packets/s on the
  bench. The per-line path stays for network connections only.
- `StreamSample.extra` keeps fields after the fourth (1.4.6 already
  sends a fifth). `StreamStats` records which reader ran and any port
  failure.
- The fake miniSMU now streams bytes through a fake serial port in the
  measured format, with whole-millisecond stamps and an optional rate
  error. Tests cover packets split across reads, the per-line fallback,
  and a delivered rate that differs from the requested one.
- On the bench, the bulk reader:
  - read 1009 Hz at 1000 requested, and 1409 Hz (the instrument's
    ceiling) at 2000;
  - kept the 60 s backlog flat (52 ms median arrival latency);
  - streamed both channels cleanly.
- Found while running it:
  - periodic stamp bunching (~every 100 ms);
  - a clock offset to the Pi: +306 ppm over 60 s, but about −95 ppm in
    two 10 s fits, so it needs longer runs to pin down;
  - open-lead noise of ~14.5 nA RMS, repeatable, of which **89 % is
    50 Hz mains pickup**.
  - All recorded in `docs/hardware.md`. Architecture: notch or
    whole-cycle averaging in Phase 3's binning.

## 0.1.4 - SSH setup fixes in the runbook

- `docs/bench.md` explains `ssh-keygen`'s questions: keep the default
  file, leave the passphrase empty (Claude connects without a terminal
  to type one), and keep an existing key.
- It also addresses the Pi as `<name>.local` (avahi) rather than by IP,
  which changes between networks, and explains why `hostname -I` shows
  several addresses.
- Laser firmware 2.0.0 compiled and flashed. The board answers
  `MultiLBIC-Laser,2.0.0` over SSH.
- All four USB devices identified by serial number. The laser Xiao is
  line 3 of `Serials.txt`; line 1 is the retired instrumentation Xiao.
- `machine.toml` names the Pi's ports by `/dev/serial/by-id/` path,
  which is stable across replugging and needs no udev rules, instead of
  the old rules' `/dev/SKR`-style names.
- Runbook: clone with `--branch` (a plain clone lands on `main`, which
  has no `setup.sh` yet). Warns that the first install downloads over
  100 MB.
- First bench session over SSH (no motion, no lasers):
  - all four devices answer, and the hardware tests pass;
  - the running Marlin settings differ from compiled: A/B at 6 mm/s,
    600 mA, StallGuard 130;
  - the miniSMU streams up to ~1.2 kHz with whole-millisecond stamps,
    but its delivered rate is not the requested one, and per-line
    reads can't keep up on the Pi (bulk reads can);
  - noise at 0 V is ~1.5 nA RMS on the low ranges.
  - Findings are in `docs/hardware.md`.
- First SSH check of the Pi recorded:
  - the SKR and the TFT35's FTDI adapter identified;
  - there are no udev rules on the Ubuntu install;
  - the `sudo` steps are yours, because `sudo` needs a password.
- The miniSMU firmware upgrade is optional for the first session.
  Undalogic's updater fails server-side (HTTP 500), and 1.4.6 streams,
  just without the current range in each packet.

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
