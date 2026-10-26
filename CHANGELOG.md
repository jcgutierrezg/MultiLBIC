# Changelog

Newest first. Versions follow MAJOR.SESSION.PUSH, as in SMUniversal.
From Phase 4 on, the middle number is the phase.

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
