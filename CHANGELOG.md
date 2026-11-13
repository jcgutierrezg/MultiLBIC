# Changelog

Newest first. Versions follow MAJOR.SESSION.PUSH, as in SMUniversal.
From Phase 4 on, the middle number is the phase.

## 0.7.27 - The laser board's schematic, as a draft

- hardware/laser-board-schematic.md: the laser board drawn as four
  sheets (supply, enable and lid; a channel; the DAC and its bus; the
  ESP32 and outputs), to redraw in Fusion, with every net, designator
  and pin number and a layout guide. The sheets are SVG, drawn by
  `hardware/laser-board/sheets.py`. The DAC's pins checked against its
  datasheet, the DevKit's against Espressif's guide.
- Drawing it changed the bill of materials. The enable goes through a
  MOSFET: driven directly, an unpowered ESP32 held the line near 1 V,
  where the clamps are not surely on, so a laser lit when the Pi lost
  power could stay lit. GPIO21 is now high for "enabled". The lid
  switch sits between that MOSFET and ground and the ESP32 reads the
  same line.
- Also: 10 nF at each set point; no 10 kΩ in the drain and rail
  readbacks; the spare amplifiers tied off at half the supply; the
  DAC's decoupling; lamp and aux about 0.2 A together, behind the
  polyfuse, not 0.5 A each.
- The 5 V input, lamp and aux sockets are 3-pin with the middle pin
  unused, so a laser's 2-pin plug in one meets a single live pin at
  most.
- Noted: the DAC's zero leaves up to 30 µA in each unlit laser while
  another is lit.
- plan.md: a 12 V buzzer on the SKR's FAN0 socket for "run finished"
  and errors (`M106`/`M107`; in the laser board's BoM), and exhaust
  fans for the box, always on, from the 12 V input.

## 0.7.26 - Six channels, their current and voltage read back

- hardware/laser-board.md: six channels, not eight (no use for spares).
  Each reads back its current and its module's voltage, and the rail is
  read too: 13 analog inputs, which WiFi and Bluetooth never being on
  frees (the S3 has no DAC, hence the external one). One enable for all
  six (a clamp on each set point, cut by the lid in hardware) instead of
  six, so the pins fit.
- Every pin assigned, clear of the S3's strapping pins (GPIO0, 3, 45,
  46), its USB (19, 20), UART0 (43, 44), octal PSRAM (35-37), the dev
  board's RGB LED (38, 48) and GPIO47: 20 of the 22 safe pins used.
- The temperature from a thermocouple through an MCP9600 module on the
  DAC's I²C bus, not a one-wire sensor.
- A draft bill of materials replaces the indicative parts: per channel
  and shared, hand-solderable, with quantities. 1 MΩ drain dividers, so
  an unlit laser carries 2.5 µA, not 25 µA; the board sits inside the
  box, so no LEDs on it, and the dev board's and the MCP9600
  breakout's power LEDs are removed or covered; the aux output
  switches 5 V.
- The revolver's mount decided: a ring as now, about 40 mm radius, the
  six lasers at 60° in wavelength order with the homing tab in the gap
  between 6 and 1, split clamps at one height, printed and clamped
  straight on the NEMA 17's shaft, leads in a slack loop. Held or
  released after a move is decided once it is built.
- On a scope (hardware/lasers.md): lasers 1, 3, 4, 5 and 6 give steady
  light with no ripple, on their own drivers or the plain supply. Laser
  3's driver is not pulsed or switching; lasers 1 and 2's trouble under
  a forced voltage was the miniSMU's loop, not pulsing. Left for the
  prototype: lasers 1 and 2 on the board's own current loop.
- A temperature stage is for later and needs nothing on this board:
  the SKR's free heater, fan and sensor pins and Marlin's loops cover
  it. Noted: Marlin reads thermocouples only through a MAX31855 on SPI
  (no MCP9600 driver), and `PELTIER_BED` is only in bugfix-2.1.x.
- The classic ESP32 (NodeMCU-32S) was weighed and set aside: 11 safe
  analog pins of the 13 needed, an ADC blind below 0.1 V (10 mA), and
  a reset when the port opens. The S3 stays.

## 0.7.25 - The revolver needn't be precise

- hardware/laser-board.md: every run locates each laser on the
  photodiode (D29), so the revolver's stepper only has to land each
  beam where the locate finds it; the plan no longer asks the bench for
  servo-grade repeatability or finer microsteps.

## 0.7.24 - All six modules, and a laser board proposed

- All six laser modules measured on the miniSMU, written up in
  hardware/lasers.md: lasers 1 and 2 are plain diodes (laser 2 held just
  under its 28.4 mA threshold by today's 3.26 V, hence its weak and
  drifting light); laser 4 has a regulator; lasers 3, 5 and 6 have
  drivers that take over above a current. Every one is a clean diode
  under a forced current below that point.
- Lasers 1 and 2 don't settle under a forced voltage; the miniSMU did,
  into 100 ohm, to 4 V within 2 mV (hardware/smu.md).
- hardware/laser-board.md: the proposed board. Eight identical current
  sinks on an ESP32-S3 with readback, the lasers on the SKR's 5 V
  with a bulk capacitor and the ESP32 on the Pi's USB, every laser run
  on current below its switch point (or on its own driver, per laser),
  the servo replaced by a NEMA 17 on the SKR's free Z driver homed
  against a tab (direct, 16 microsteps, all six at one spot), an
  interlock, a laser-on lamp, lasers off when the Pi goes
  away, a temperature sensor, two spare channels.
- The module test calls a jump to the voltage limit with the light up
  10 % a driver (laser 6: the current down 3 %, the light up 38 %), and
  says when its plain-supply sweep stopped at the light ceiling.

## 0.7.23 - A gentle bend low down is noted, not a stop

- Laser 5 stopped at 14.5 mA on its light per mA easing to 85 % of its
  best, at a quarter of its light ceiling: too conservative for
  characterising it (the operator's call). Below half the ceiling a
  gentle bend, still there read again, is now noted in the report and
  the verdict and the sweep goes on. A bend past half the ceiling still
  stops it, and so does a severe one at any light, the slope under half
  its best (full rollover: light flat, never reaching the ceiling). A
  fall still stops it. The 4 mW stop and the 1.5 x cap after a bend
  stand.
- The simulator's `laser5`: its diode, easing as measured.

## 0.7.22 - The limit's offset allowed for; a clamp seen by its voltage

- Laser 5's third pass completed: the limit check measured 1.23 x at
  2 mA, but its plain-supply sweep clamped at 18.06 mA for 16.85 mA
  sent (1.07 x): the miniSMU's limit clamps about 1.05 x the setting
  plus 0.4 mA, and 0.7.19's 18.76 mA was no limit at all, the limit set
  before the range. 0.7.21's note that the order "is not it" was wrong;
  hardware/smu.md now has both.
- The gain at 2 mA over-corrected at higher currents, so laser 5 sat at
  18 mA, 83 % of the 21.8 wanted, without the sweep calling it the
  limit, set to 5.5 V and read at 1.94 V. Limits are now sent at what is
  wanted less the excess the limit check read, over 1.05, which lands
  the clamp at what is wanted; and the voltage read more than 30 mV
  below the voltage set counts as at the limit. The simulator's limit
  has an offset as well as a gain.
- Laser 5's three passes in hardware/lasers.md: a diode to 18 mA and
  1.55 mW on a plain supply, its driver above that, as laser 3's.

## 0.7.21 - Channel 1's limit clamps 1.22 x: measured and allowed for

- 0.7.20's laser 5 run: the limit check read 2.69 mA under a 2.2 mA
  limit, where 4.34 mA flows without one, and stopped the run (below
  threshold). With 0.7.19's 18.76 mA through 15.5 mA, the miniSMU's
  voltage-mode current limit clamps about 1.22 x what is set; the
  range-before-limit order of 0.7.19 was not the cause (corrected in
  hardware/smu.md).
- The limit check now measures that gain (read over sent), stops the
  run if the limit doesn't act (above 80 % of the current without it)
  or the gain is past 1.5, and every later voltage-mode limit is sent at
  what is wanted over the gain and 5 %. A current past 90 % of the
  wanted limit counts as at it.
- The simulator's limit has a gain; tests at 1.22 x and at 20 x.

## 0.7.20 - Channel 1 parked in voltage mode

- 0.7.19's laser 5 run refused its dark: channel 2 at +0.156 V. On the
  bench, channel 2 goes offset whenever channel 1 is in current mode
  with its output off (its mode command, a current level or the output
  off set it there), and a mode command in voltage mode sets it too;
  channel 1's range or its output on clears it. 0.7.19 parked channel 1
  in current mode. It now parks in voltage mode at 0 V (mode, range,
  1 mA limit, 0 V), and three dark-only runs on the machine read +0.11
  to +0.15 uA. The rule is in hardware/smu.md.
- The simulator's channel 2 goes offset by the same rule, so a run
  that reads in that state fails the tests.

## 0.7.19 - Channel 1's current limit, set after its range

- Laser 5's second pass: its voltage sweep let 18.76 mA through a
  15.5 mA limit, and the probe's check of every reading stopped it
  (about 1.6 mW, harmless). The limit was set before channel 1's range,
  and a range command sets the limit to the range's full scale. No
  earlier run had reached a voltage-mode limit, so the dry run's "the
  limits held" never covered it. Each channel is now mode, range, then
  limits and level; the simulator's range command resets the limit as
  the real one does.
- Before the voltage sweep and holds, the probe proves the limit on the
  instrument: the voltage that drew half the lasing threshold, under a
  limit of half that. Not held, the module sits below threshold and the
  run stops.
- After a curve that bent, the voltage sweep's limit is up to 1.5 x
  the highest current reached (still under the light extrapolation),
  not that current: laser 5's mild bend would have kept it below where
  its driver takes over. After a fall it stays at that current.

## 0.7.18 - Every lasing module on a plain supply

- Laser 5's first pass stopped for "curve bending" at 14 mA: one dip in
  its light (its 60 s holds dipped up to 6 % at random). A bend or fall
  is now read again at the same current, no higher, and stops the sweep
  only if it holds; the points read again are in the report.
- On the board laser 5 draws 16 mA for twice the light its diode curve
  gives there, so it too has a driver; but only a module already seen
  regulating got the voltage sweep to 5.5 V. Every module that lases
  now does, under a limit from the straight diode curve (the highest
  current reached, if it bent); my 1.25 x cap on it is gone.
- The verdict describes a gradual hand-over on a plain supply (laser 3:
  current peaking at 22.8 mA at 2.50 V, falling to 16.0 mA by 3.9 V) and
  a sweep that sat at its limit. Lasers 3 and 5 in hardware/lasers.md.

## 0.7.17 - Laser 3's driver, and modules on a plain supply

- Laser 3 (2026-11-10): a plain diode to 22.5 mA; forced to 23 mA the
  voltage jumped to 5.5 V and the current fell to 16.6 mA while the
  light held 3.16 mW, more than that current gives it as a diode. It
  stayed so coming down to 16 mA. The test called it "regulated from
  16.6 mA, needing 5.54 V" and the two states 58 % hysteresis.
- A jump to the voltage limit with the current falling is now "a driver
  inside": where it switched, the current, voltage and light after, and
  down to where it stayed switched. Hysteresis compares up and down on
  the same branch only.
- For a module with a regulator or driver, the voltage sweep goes to
  5.5 V under a limit that keeps the plain-diode curve below the light
  ceiling, and the verdict gives where it switched over and its current
  and light at 3.3 V, 5 V and `--v-known`; the voltage hold is at
  `--v-known` when the sweep passed it. The PNG has a fourth panel,
  light and current against the voltage.
- The simulator's `laser3` has that driver.

## 0.7.16 - The laser module test finds a regulator's knee

- Laser 4 (2026-11-10): lasing from 16.5 mA at 0.555 mW/mA, then its
  own regulator from about 22.5 mA, the voltage climbing from 25 ohm to
  530 and 1900 ohm per amp while the light held at 3.45 mW, which is
  what the board gives it today. The test stopped for "curve bending"
  and called it "no regulator": it only knew a regulator by the
  voltage reaching 5.5 V.
- The sweep now stops at a regulator's knee, volts per amp past 8 x
  their median over the mA before (and past 200 ohm), and the verdict
  gives where the regulator takes over, the voltage it needs and the
  light it holds, and the rail for the board from that voltage.
- The simulator's `laser4` has that soft regulator.

## 0.7.15 - Channel 2's offset state, set and cleared

- Every 0.7.14 run refused its dark: +298-300 uA on 15 mA. On the bench
  (channel 1's output off) a mode command to channel 1 puts channel 2
  in its offset state, +0.30 V reported at 0 V and about 2 % of the
  range's full scale read; the next fixed-range command to channel 1
  clears it. Channel 2's own range, a reset and replugging didn't.
  Written up in [smu](docs/hardware/smu.md#the-channel-2-offset-state).
- The laser module test parks channel 1 before its dark (current mode,
  0 A, output off, its range last) and refuses any reading with channel
  2 more than 10 mV off 0 V. Three dark-only runs on the machine read
  -0.06 to -0.09 uA.
- The simulator can put channel 2 in that state.

## 0.7.14 - The laser module test checks its dark

- Laser 4's second run read the photodiode +297 uA dark for its first
  second on the 15 mA range and -0.25 uA after, so all its "light" was
  that offset (curve bending stopped it at 1.5 mA). With the offset the
  other way the light would read low and the ceiling sit high. The dark
  is now read 2 s after channel 2 is set up, refused if more than 20 uA
  from 0, and read again at 0 mA before and after the current sweep:
  more than 2 uA from the dark stops the run.
- The prompt says the beam check's current (1.5 x `--i-known`).
- The simulator can offset channel 2's first readings.

## 0.7.13 - The laser module test reads past 1 mA

- Laser 4's first run read its light flat at 1.01 mA and stopped for
  "curve bending" at 21 mA: the photodiode channel was autoranging,
  which holds it to 1 mA whatever limit is set. It now sits on the
  fixed 15 mA range, a reading near that range's end stops the run, and
  "lit" is 0.5 uA or 10 x the dark's scatter, whichever is more.
- The voltage stage and the holds are where the light reached 80 % of
  its peak, not at 80 % of the highest current, which put laser 4's
  holds below its 16.5 mA threshold.
- The simulator's channel 2 clips as the real one does, and a `laser4`
  module, as measured, reproduces the first run's stop.

## 0.7.12 - The lasers on the power meter

- `machine.toml`: the photodiode's response to lasers 1, 3, 4, 5 and 6
  from the Power tab (PM100USB, S120VC, 2026-11-10): 3-6 within 4 % of
  the datasheet, laser 1 +8 %. Laser 2 drifted 44-77 % within each of
  three tries and keeps the datasheet's. Laser 5's position from its
  photodiode found again: it had moved 0.89 mm along X.
- Docs: the powers in [lasers](docs/hardware/lasers.md), and in
  [commissioning](docs/commissioning.md#power) what a −99 % or a
  drifting calibration means.
- Tests no longer assume no laser is calibrated: the laser module's
  light ceiling is tested with and without a power-meter response.

## 0.7.11 - A laser module on the miniSMU

- For the new laser board: `python -m multilbic.bench.laser_module`
  measures how a module takes power, wired straight to channel 1 with
  the photodiode on channel 2. Stages: dark; current forced up to a
  stop and back down (the voltage it needs, light against current:
  threshold, slope, kinks, hysteresis, and a regulator showing as the
  voltage jumping to the limit); voltage forced up to the voltage at
  80 % of the highest current reached; and 60 s held at that voltage,
  then that current. A verdict, a JSON report and a PNG.
- The limits are absolute, not today's operating point (lasers 1 and 2
  are starved there): current steps shrink near the light ceiling, and
  the sweep stops at the first of 5 mW of light (80 % of it as the
  power-meter-calibrated photodiode reads; 65 % with
  `--datasheet-response`, refused otherwise), the curve bending 15 % or
  falling, 5.5 V or 120 mA. Every level is zero or positive, zero before
  off or a mode change; a reading past a ceiling ends the run.
  `--i-known` (today's current) only checks the beam is seen: light by
  1.5 x it.
- `--polarity-check` (+1 V, 1 mA limit, nothing connected) finds
  channel 1's +; `--dummy-load` dry-runs every stage on a resistor and
  says whether the instrument held its limits.
- `sim/laser_module.py`: regulated, resistor, starved, rollover and
  dummy modules on a fake miniSMU that sources current as well as
  voltage.
- Runbook: [bench](docs/bench.md#testing-a-laser-module).

## 0.7.10 - Flip the photocurrent's sign in the viewer

- **Flip sign**, beside the viewer's Show switch: the photocurrent
  (negative as wired) shown with its sign flipped everywhere it is
  read: maps, colour bars, typed limits, cursor, profile and spectrum,
  labelled "−photocurrent". Ratios are unchanged; greyed out for EQE,
  which is positive already.

## 0.7.9 - The spectrum at a pixel or over an area

- Phase 7 step 7. The viewer's Profile section is now **Line or area**:
  **Drag draws** a line (the profile, as before) or an area. In area
  mode a click picks one pixel and a drag a box, drawn on every panel
  to the edges of the pixels it counts; the plot shows every laser's
  value there at its wavelength, the median and the 16-84 % spread, as
  EQE or photocurrent as **Show** says. A laser with nothing there is
  named.
- The line and the area each stay through changes of laser, view and
  quantity; **Clear** clears the one the mode draws.
- `viewtools.area_mask`, `spectrum`, `SpectrumPoint`.

## 0.7.8 - The Power tab: the photodiode against the power meter

- Phase 7 step 6, second half (D32 revised): the Maintenance window's
  **Power** tab measures the photodiode's response to one laser with the
  power meter. Photodiode before (dark, laser on and warmed up, range
  chosen, read), the meter's reading typed with its head at the
  sample's place, photodiode after on the same range, then the dark.
  The response (before and after's mean, dark out, over the meter's
  power) is shown with what is worth a second look: before and after
  more than 2 % apart, more than 25 % off the datasheet, a reading at
  its range's limit. **Save** writes `pd_response_a_w` and
  `pd_response_date` into the laser's table.
- `run/powercal.py`: `PowerCal`, `PowerCalibrator` (on commissioning's
  readings), `apply_response`, a report per calibration in the runs
  folder. The worker's `power_before`, `power_after`, `save_power` and
  `PowerCalChanged`; Stop reaches it as it reaches commissioning.
- On the simulator: laser 3's response comes out as the simulated
  photodiode's full beam over the meter's reading, within 3 %.

## 0.7.7 - Maps as EQE

- Phase 7 step 6, first half (D32 revised). `scan/eqe.py`: a pixel's
  EQE from the cell's current over the photodiode's at that row's time
  (the power before and after, dark out, a straight line between), the
  photodiode's response to the laser and 1239.84 / wavelength.
- The response, in order: measured with a power meter and recorded in
  the run's header; measured since, in `machine.toml` now; the
  S1223-01's typical curve from Hamamatsu's datasheet (KPIN1050E02, Feb.
  2013: 0.45, 0.52, 0.54 and 0.60 A/W at 660, 780, 830 and 960 nm from
  its table, the rest read off its graph). New per-laser keys
  `pd_response_a_w` and `pd_response_date` in `machine.toml`, copied
  into each run file's header.
- The viewer's **Show: Photocurrent / EQE**, in every view, the cursor
  and the profile, in %; the caption says which response the EQE rests
  on and how far the power moved. A map without power readings says it
  has no EQE.
- A simulated laser drifting 8 % a second: the current rose 6 % across
  the cell, the EQE 0.1 %.

## 0.7.6 - Each laser's power before and after its map

- Phase 7 step 5, in the simulator (D31). A laser located on the
  photodiode now: the cell's baseline where the locate left the stage,
  laser off; the warm-up on the photodiode's open quarter, read once a
  second; its power at the end; the stage back to the sample and the
  rows, on a stream started again on the same device clock
  (`stream.start(set_clock=False)`); after the last row, the power
  again and the photodiode's dark on the same range. A laser placed
  from `machine.toml` runs as before.
- In the run file: `warmup_on`, `power_before` (with the warm-up's
  curve) as a note after the baseline (`RunWriter.note`), `power_after`
  and `power_dark` in the trailer. A reading after the map that fails
  is written down (`power_after_error`); the map stands.
- `run/locate.py`: `Locator.warm_up`, `power_after`, `PowerReading`,
  `PhotodiodeStops`; `LaserFix.range_a`, the photodiode's range. The
  estimate counts 20 s a laser for it (`LaserEstimate.power_s`).
- The simulator's lasers drift on request (`Faults.
  laser_drift_per_min`), on the cell and photodiode alike; a test
  checks the readings follow it to 1 %. Located maps still line up as
  before (the locate tests).
- D32 revised: EQE from the photodiode's response to each laser,
  measured with a power meter and kept in `machine.toml`; the datasheet
  curve only for a laser not measured. Step 6 gains a Power calibration
  tab. The new laser board (power per laser, normalised) is under
  "Later", its open questions with it.

## 0.7.5 - Lasers compared

- Phase 7 step 4, in the viewer, above the map: **One laser**, **Side
  by side** (every laser in a panel of its own, in one unit, with one
  colour scale or each its own) and **Ratio** (one laser over another,
  pixel by pixel, picked in two boxes). The panels are laid out as big
  as the area allows (`viewtools.panel_grid`); a click on one makes that
  laser the current one.
- A ratio's pixel is blank where the laser below gives under 5 % of its
  own top value, or either is empty (`viewtools.ratio`).
- The cursor reads every laser shown, and the ratio; the line is drawn
  on every panel, and the profile plots each laser's in its colour, or
  the ratio. Reload keeps the view.
- On `20261106T163140Z_full_test`: laser 6 over laser 1 is about 3.9
  across the cell.

## 0.7.4 - Each map's alignment, saved beside it

- A map's serpentine shift and its late rows' placement are saved in
  `laser<N>_<nm>nm.align.json` next to its file (`store/alignfile.py`):
  how the shift was found (computed or by hand), by what, when, with
  which version, and the file's size and rows it is for. The run writes
  it as each laser's map ends; the viewer, `multilbic map` and the
  window's "Open run file" build from it while it matches the file, and
  otherwise search again and save it. D30 revised: the viewer writes
  these files, nothing else.
- The viewer's Alignment section shows it, with **Re-align** (search
  again with the code as it is now) and **Set shift** (a shift typed in
  µm, kept). The map redraws with the same line and colour limits.
  `multilbic map --realign`.
- `build_map(alignment=, late_from_reply=)` uses them instead of
  searching; `MapResult.late_from_reply` says which late rows took their
  reply. Same map, checked on real and simulated runs.
- `read_run` parses the numbers with `np.loadtxt`: 2.9 s to 1.3 s for a
  120 MB file, identical on all 38 run files on the PC; a half-written
  last line is left out.
- `20261106T163140Z_full_test` (three 18 x 20 mm maps): 74 s to open the
  first time, 9.6 s after.
- The line-up and the sync check still search afresh: they are
  measurements.
- The laser colour dots (`look.swatch`) are kept per Tk interpreter: a
  second Tk reuses the same widget paths, and the viewer's tests, run
  after the window's, got a dot from a Tk already gone.

## 0.7.3 - The viewer, one map

- Phase 7 step 3: `multilbic view [FOLDER]` (`gui/viewer.py`,
  [viewer](docs/viewer.md)), its own window on the PC and the Pi,
  reading run folders only. Open a folder (read on a thread, the footer
  saying which file), pick a laser (or keys 1-6), and its map is drawn
  as the machine window draws it, with matplotlib's zoom and pan.
  Colour limits auto (1-99 %), full or typed; the value under the
  cursor; a line profile dragged across the map, kept when another
  laser is picked. Reload reads a run still going again.
- `gui/viewtools.py`: the viewer's arithmetic without Tk (plot point to
  u, v, the pixel and value there, profiles, colour limits, the unit a
  map suits), on mypy's list.
- `store/image.draw_map` and `image_data` take the unit to draw in
  (`per_unit_a`, nA by default, as before): a 1 mA cell is drawn in mA,
  not as -1000000 nA. `RunFolder.started`.
- The simulated two-laser run the tests open is made once per session
  (`conftest.run_folder`).
- On three real runs from the Pi: the 2026-11-05 corner and 2026-11-06
  line-up runs open in under 2 s; `20261106T163140Z_full_test` (lasers
  1, 3, 6, 18 x 20 mm) in 80 s on the PC, 85 % of it the serpentine
  alignment's pair shifts.

## 0.7.2 - The fix for count-dating merged in

- main merged into Phase 7: PR #9 (0.6.56-0.6.57). Samples lost here
  and there keep their stamps instead of being dated by count, which
  had combed `20261106T145401Z_full_test`'s first map; a laser the
  locate can't find gets a second, broader try, then the run asks
  (place it from `machine.toml`, skip it, or stop).
- Nothing of Phase 7's changed: `read_folder` builds maps through
  `RunFile.scan_data`, so it dates samples the new way too.

## 0.7.1 - A run folder as one set of maps

- Phase 7 step 2: `multilbic/store/runfolder.py`, `read_folder(folder)`.
  Every laser's map in a run folder is built again from its file and
  put on one grid in the sample's u, v, with the run's details from
  `run.json`, `calibration.json` and the file headers (wavelength,
  status, range, where each laser was located, alignment, noise floor).
  A run's lasers share the frame, so their grids are used as they are;
  grids that differ are resampled, nearest pixel, onto the finest.
- Clipped attempts are listed and not mapped; a file that can't be read
  is reported and the rest still open; a run still being written opens
  with the rows it has. Reads only.
- On two real six-laser runs copied from the Pi (2026-11-05 corner,
  2026-11-06 line-up): all six maps on one grid, about 1.3 s a folder.
- `runfolder.py` is on mypy's list; tests in `tests/test_runfolder.py`.

## 0.7.0 - Phase 7's plan: the viewer and spectral response

- `docs/plan.md`: Phase 6 closed (PR #8); Phase 7 planned with nine
  steps, ending in a bench run and one PR. The viewer, `multilbic view`,
  is its own window for run folders on the PC and the Pi: one map
  explored, the lasers compared, EQE maps and the spectrum at a pixel.
  Runs will read each laser's power on the photodiode before and after
  its map, warming up on the photodiode.
- Decisions D30 (the viewer), D31 (power before and after each map,
  interpolated in time), D32 (EQE from the S1223-01's datasheet curve),
  D33 (option C dropped).
- Tiling, exports, laser health, the TFT35 pendant, Pi polish and Phase
  6's leftovers are under "Later".
## 0.6.57 - A laser that can't be located: again, then ask

- The same six-laser run stopped at laser 2: its locate failed, and
  with it the run, so lasers 3-6 never ran. Laser 2 gives a fifth of
  its light of yesterday (7.9 µA on the photodiode), a hardware matter.
- A laser the locate can't find now gets a second try with broader
  sweeps (±0.8 mm round each edge, ±3 mm for the full sweeps). If that
  fails too, the run asks: place it from `machine.toml`, skip it and go
  on, or stop. The window asks in a dialog; `run` on the terminal, or
  as `--if-not-located place|skip` says (without a terminal it skips).
  The choice is in the event log, `run.json` and the laser's header.

## 0.6.56 - Samples lost here and there keep their stamps

- A six-laser run on an 18 x 20 mm cell at 5 mm/s (1000 Hz,
  `20261106T145401Z_full_test`): laser 1's live map looked right, its
  finished map came out combed, the cell's outline a circle, "serpentine
  shift not found". The stream had lost about 3 % of its samples, a few
  at a time, none long enough to count as a break, so dating them by
  count drifted −320 to +775 ms over the 30 minutes. A stretch whose
  line misses its stamps by more than 6 ms now keeps its stamps: that
  map then aligns at +152 µm and is clean. 800 Hz maps lost nothing and
  are dated by count as before (the line-up's shifts unchanged to 5 µm).

## 0.6.55 - A commissioning test that held on Windows CI

- `test_a_measured_corner_stays_and_the_reference_laser_moves` compares
  two simulated commissioning runs; on Windows CI one put laser 3
  12.5 um from the other, where the test allowed 3 um. A host stall of
  a few ms becomes 50 times that in simulated time on the slow passes'
  anchors. It now runs at 25x and allows 10 um between the runs (the
  laser moved is 300 x 200 um); precision against the truth is still
  checked to 3 um in the first commissioning test.

## 0.6.54 - The lockfile follows the version

- `uv.lock` had stayed at 0.6.17 while the version moved on, so CI's
  `uv sync --locked` refused the branch. It is locked again and
  committed; from now on it goes in with every version bump.

## 0.6.53 - Docs as the machine is now

- Every doc read again against the machine as it stands; what was no
  longer true or useful is gone (git history and this changelog keep
  it): the placeholder laser positions, the old stage's readings, the
  first commissioning across the can's window, finished bench runbooks.
- `docs/hardware.md` (1,473 lines) is now an overview with five pages
  under `docs/hardware/`: lasers, motion, smu, photodiode, timing.
- `docs/run.md` split: focus, commissioning and the line-up in
  `docs/commissioning.md`; `read`, `sync-check`, `edges` and the device
  probes in `docs/diagnostics.md`.
- `docs/bench.md` is now working on the machine (safety, deploying,
  results); SSH and Ubuntu setup moved to `deploy/pi/README.md`.
- `docs/plan.md` keeps what is open; the decisions moved to
  `docs/decisions.md`, with D6, D9, D14, D22 and D27 brought up to date
  and D29 (each laser placed from the photodiode) written down.
- Code comments that pointed at moved sections point at the new pages.

## 0.6.52 - The second line-up, and Go to photodiode

- **Go to photodiode** on the Lasers panel brings the middle of the
  photodiode's open quarter under the laser that is on (homed, a laser
  on, a photodiode in `machine.toml`).
- Hardware notes: the second line-up, with the saved offsets. The
  lasers spread 39 um along u and 29 um along v, from 86 and 116 um:
  about their run-to-run scatter, so the offsets stay. Laser 2 gave
  less light than the day before and needed the full sweeps to locate.

## 0.6.51 - The first line-up, and rows that start late

- The first line-up on the bench (`20261105T181317Z_lineup_test-lineup`):
  every laser's two cell edges found, laser 2's too. Against laser 3,
  the lasers sat 8-86 um off along X and up to 108 um along Y; the
  offsets are saved in `machine.toml` (`cell_offset_xy_mm`).
- Lasers 5 and 6 each had a row or two drawn 100-200 um off. Their
  replies were 27-45 ms late, but these were single rows, and their
  moves had started late too: placed from the send, as 0.6.47 does for
  late replies, they were wrong; from the reply, right. A late row now
  keeps whichever placement lines up with the on-time rows of its own
  direction near it; with none to compare, the send, as before. Every
  map of the day still aligns at +110 to +157 um, and the line-up's
  offsets move by 1 um at most.
- The simulator can take a line up late (`Faults.late_lines`); a test
  shows such a row stays in place. Its beams land on the cell where
  `machine.toml`'s offsets say, as they land on the photodiode where its
  `xy_centre_mm` says.

## 0.6.50 - The Maintenance window and the line-up

- **Maintenance...**, at the window's bottom left, opens a window with
  three tabs: **Focus** (focus assist, moved out of the Lasers panel),
  **Photodiode** (commissioning, as `multilbic commission`) and
  **Line-up**. Each shows what it found and writes `machine.toml` only
  on Save.
- **Line-up**: a run over a 1.2 mm square centred on the calibration's
  corner (set on a cell's corner), every laser placed from the
  photodiode; then each laser's two cell edges against the reference
  laser's, and the offset that puts its map on the reference's
  (`run/lineup.py`, also `multilbic lineup RUN [--write]`).
- New per-laser `cell_offset_xy_mm` in `machine.toml` (optional, 0),
  added wherever a laser is placed on a sample, and recorded in each
  run file. In the simulator, which can now land a beam elsewhere on
  the cell than on the photodiode (`Faults.cell_offset_xy_mm`), offsets
  of 30-40 um are found within 5 um and, written, put the next
  line-up's lasers within 6 um.
- **The reference laser is laser 3** (was 2, the dim one). Calibrations
  made under laser 2 stay right.
- Re-read with the line-up's edge finding, the earlier six-laser runs
  put laser 2 among the others along u (0.372-0.375 mm), and the
  "laser 3 lowest along v" was an edge too close to those patches'
  start to measure: the line-up centres its patch for that reason.

## 0.6.49 - No mains put into the rows

- Laser 6's alignment chose about 80 um where its edge says 120-137.
  The mains removal did it: fitted over the whole row, the cell's 1 mA
  edge leaked about 1 % into the 50 Hz sines, about 10 uA of ripple
  subtracted *into* a row whose own mains was too small to show. The
  ripple repeated row to row, and the fine-scale alignment locked onto
  it one mains cycle (80 um at 4 mm/s) off.
- The sines are now also fitted where the row is flat only, against a
  one-cycle moving average that holds no mains; that fit is used unless
  it is more than twice the whole row's (features shorter than a cycle,
  which only the whole row's fit averages out). Beside a 1 mA edge the
  mains now comes out to a tenth or better, where it was put in at 300
  times its size.
- All 30 maps of the day's five six-laser runs align at +110 to
  +157 um; laser 6's at +115 to +132. In the last run, its edge spread
  over rows halved (36 to 19 um).

## 0.6.48 - Six lasers repeat within 20 um

- Hardware notes: a third six-laser map (0.6.47). Every laser put the
  cell's edge along B where it did in the second run, within 18 um;
  five of the six within 16 um of each other, laser 4 35 um short of
  them in both. Along A they spread 100 um, each laser where it was
  before (laser 3 lowest), within 2-21 um.
- Two of its maps had late replies throughout (lasers 1 and 4, 27 rows
  each); placed from the send, their shifts were +120 and +133 um.
  Laser 6's alignment chose +82 um where its edge says +137, as in the
  first run: still to look at.

## 0.6.47 - Late replies placed from the send

- The serpentine shift's sign flips (3 of 12 maps on 2026-11-05, 4 of
  24 in the day's four six-laser runs) were Marlin's `ok` to a row's
  `M400` coming 20-40 ms late, for a stretch of rows or a whole map.
  The rows were placed that much late: at 4 mm/s, a shift of +130 um
  became -68 to -196 um. The samples' timing was clean.
- Maps now place a row whose reply is late from when its `G1` was sent
  instead (`scan.timing.settle_late_replies`): the send plus the usual
  delay plus the move. The usual delay is the file's own, from its
  quickest replies, or `[ab] row_reply_ms` (93.5 ms, new, optional)
  if even those are late. All 24 maps of the day then give +110 to
  +157 um, and their two directions meet on the cell's edge. Run files
  record `row_reply_ms`; older ones are read with the bench's.
- The simulator can answer `M400` late (`Faults.m400_late_s`); a test
  shows the map unchanged by it.

## 0.6.46 - Six lasers within 60 um

- Hardware notes: two six-laser maps located on the photodiode with the
  servo released. In the second, all six lasers put the cell's edge
  along B within 57 um of each other (370 um in the last located run
  with the servo powered). Along A, lasers 4-6 agree within 30 um and
  laser 3 is 70-90 um off in both runs.
- Between the two runs, lasers 1, 3, 5 and 6 repeated within 25 um.
  Laser 4 moved 65 um and laser 2, the dim one, 160 um.
- The serpentine shift came out negative for three of the twelve maps,
  and each such map's two directions still agree: the timing changed
  for that map, not just the alignment's choice.

## 0.6.45 - The released servo holds

- Hardware notes: with firmware 2.1.0 flashed and the servo released,
  the spot stopped jumping. Laser 4 with the stage still held to 0.3 um
  for 60 s and moved under 2 um in each 2 min after a swing (7-24 um
  jumps before); laser 3 tracked by the stage moved 4-11 um in each
  2 min after a swing (60-106 um before). Each selection still lands
  the laser 7-42 um from the last, which locating on the photodiode
  measures.
- Firmware 2.1.0 is on the board (flashed 2026-11-05).

## 0.6.44 - The servo released after each turn

- Laser board firmware 2.1.0: once the servo has turned and settled it
  is released (its control pulses stop), and attached again only for
  the next turn. Held powered, it moved the beam in steps of 7-24 um at
  random times, for minutes after a turn and with the stage still
  (bench, 2026-11-05). `RELEASE?` and `RELEASE <0|1>` read and set it.
  To be flashed and tried on the bench.
- `[laser_board] release_servo` (optional, default true): the driver
  sets it at every `open()`. 2.0.0 has no such command, and is still
  accepted as it was.

## 0.6.43 - Each laser placed from the photodiode

- Runs locate each laser on the photodiode right after selecting it
  (`run/locate.py`: its open quarter, the dark, a +-0.4 mm sweep and a
  pass up and down across each blade edge, about 40 s) and place its
  map from where it is, not from `xy_centre_mm`: the servo lands a laser
  within about +-0.1 mm, differently every time. On by default where
  `machine.toml` has a measured photodiode; `run --no-locate`, or the
  window's "place from photodiode", to switch it off. The offset of
  each laser is in its run file's header and `run.json`.
- The simulator's servo can land lasers off at random
  (`servo_scatter_mm`); three lasers 34-139 um off spread about 100 um
  placed from `machine.toml` and under 25 um located.

## 0.6.42 - The servo's repeatability, recorded

- Hardware notes: the revolver's servo lands a laser within about
  +-0.1 mm, differently each selection (laser 3 on a blade edge: 0.1 um
  held still, 44 um spread along A and 20 um along B after each servo
  return), which is the run-to-run scatter of every laser position.
  A homes cleanly with a threshold of 135.

## 0.6.41 - A homing threshold per axis

- `[ab] stall_threshold` becomes `stall_threshold_a` and
  `stall_threshold_b`, each optional: only the ones set are sent. A is
  135; B is left at the board's 130. 150 on both (0.6.39) made both
  axes find a stop at once.

## 0.6.40 - The stream's last samples kept too

- A run file now also keeps the samples that arrive after the last row
  (as row -3), so it holds every sample the stream gave. On a busy Pi
  more than 50 could be left out before.

## 0.6.39 - A 5 mm/s ceiling, a homing threshold

- `[ab] max_feed_mm_s` is 5 mm/s (was 6): across the whole travel A
  vibrated at 6 mm/s and B struggled (2026-11-04). It goes to Marlin as
  `M203` at every connect too, unsaved.
- `[ab] stall_threshold` (new, optional, 0-255): the TMC2209s'
  StallGuard threshold for sensorless homing, sent as `M914` at every
  connect, unsaved. 150, up from the EEPROM's 130: A ground against the
  stop.

## 0.6.38 - Speed trials over the whole travel

- `python -m multilbic.bench.marlin ... --speeds 3,4,5,6 --speed-span
  1,39` runs the A/B speed trials across the whole travel instead of
  10-30 mm, for the repeat after the coupling's flat and the grease.
- Hardware notes: the flat is done, the rods are greased.

## 0.6.37 - The sync check, dated by count

- Hardware notes: the sync check with the stream kept whole
  (2026-11-04): L 14.9 ms, backlash +4 um, the alignment within 2-3 um
  of the edges; the stamps gave a negative backlash again. Count dating
  stays; `ab_backlash_mm` 0 and 4 mm/s stay.

## 0.6.36 - The count-dating map tests are timing tests

- The two that measure a simulated map to a few um are marked
  `sim_timing`: on the Pi the simulated scan's own timing jitters more
  than that. The line-fitting tests still run there.

## 0.6.35 - Samples dated by count, not by the SMU's stamps

- The miniSMU measures evenly but its stamps saw-tooth (6 ms every
  ~100 ms, bench 2026-11-03): samples sat up to ~12 um off along a row
  at 4 mm/s and left empty pixels. Run files now keep every sample the
  stream gives, those between rows too (row -3, `stream: continuous`),
  and maps, the sync check and `edges` date each channel's samples by a
  straight line of stamp against count (`scan.stamps`), split where the
  stream breaks. Older files keep their stamps.
- The simulated SMU can saw-tooth its stamps (`smu_stamp_saw_ms`); with
  the bench's, the edge spread at 4 mm/s falls from 7.2 to 1.7 um and
  the empty pixels from 5.9 % to none.
- Hardware notes: the sync check on the new cell (2026-11-04).

## 0.6.34 - Laser 2 warms up, recorded

- Hardware notes: laser 2 read for 3 minutes on the photodiode rises
  from -27.6 to -44.5 uA and is still climbing; the 60 s warm-up leaves
  it at about 85 %.

## 0.6.33 - The laser supply, recorded

- Hardware notes: all six lasers share one LM317 off the SKR's 5 V,
  too little headroom for green (laser 2) and blue (laser 1); turning
  its trimmer up raised those two and left the red and infrared ones
  within 5 % (a read of all six on the photodiode).

## 0.6.32 - Commissioning and focus tests are timing tests

- They run the simulated machine at 50x, and on the Pi, loaded by the
  whole suite, one missed a reply deadline now and then (passing alone).
  Marked `sim_timing`, so the Pi skips them as it skips the other
  simulator-timing tests; they still run on every change elsewhere.

## 0.6.31 - Maps without the stream's gaps, six lasers in the plan

- Map pictures (PNGs, the window's live and finished maps) fill runs of
  up to 4 empty pixels along a row from their neighbours: the miniSMU's
  stream skips 7 ms about every 100 ms, 2-3 empty 10 um pixels at
  4 mm/s, six times a row. The data keeps its gaps.
- The Plan tab's close-ups go onto more rows, evenly, when they don't
  fit side by side: six lasers were cut off.
- The miniSMU's line in the Machine panel drops the maker and the
  firmware's build hash: "MS01 v1.1, lunar-tuvok-7966, v1.4.6".

## 0.6.30 - All six commissioned again

- A six-laser map of the cell's corner (2026-11-03) had lasers 4-6
  lined up and 1-3 off by up to 1 mm; commissioning all six again found
  1-3 moved since 2026-10-30 by the same amounts. Written to
  `machine.toml`, laser 2 included (the measured corner stays).
- Bench notes: commission all six after any work in the box.
- The window's focus test waits for a good pass.

## 0.6.29 - Test windows off the screen

- The window tests build their windows transparent and far off the
  desktop, as SMUniversal's suite does, so they no longer cover what the
  person running them is working on. `MULTILBIC_TEST_SHOW_WINDOWS=1`
  shows them.
- The last tests that expected laser 4 or 5 to be a placeholder make
  one of their own.

## 0.6.28 - Lasers 4-6 commissioned

- `multilbic commission --lasers 4,5,6` (2026-10-30), written to
  `machine.toml`: positions moved up to 0.9 mm from where they were
  placed by eye, spots 98.4, 71.3 and 74.9 um, all `measured = true`.
  All six lasers are now measured.
- Tests that needed a placeholder laser make one.

## 0.6.27 - Sweeps from both sides, each finer than the last

- Each edge is swept coarse (±2 mm round where the light was found,
  0.5 mm/s), medium (±0.6 mm, 0.15 mm/s), then fine up and down. The
  coarse pass used to go one way from where the light was found, and
  laser 4's light was found on the blade itself: no full light to fit.
- Coarse and medium sweeps fit from their brightest point towards the
  blade, so the can window's far edge is left out when crossed.
- A pass that reaches the range's limit goes again one range up; an
  edge's step need only go the light's way and be at least half the
  light seen so far (the first reading may be a sliver of the spot).
- Focus assist sweeps both edges roughly before its passes, so they run
  through the open quarter's middle.

## 0.6.26 - Lasers 5 and 6 placed by eye

- `xy_centre_mm` for lasers 5 (48.4, 42.0) and 6 (49.4, 38.0) from
  where an IR card showed them on the photodiode's open quarter
  (2026-10-30); still `measured = false`. Laser 6 was 12 mm from its
  placeholder, beyond the 8 mm search. Laser 4 lit the open quarter at
  its own, which stays.

## 0.6.25 - A failed commissioning run keeps its readings

- `commission` writes `commission.json` when it fails too: the darks,
  the first reading, the passes so far (with every reading) and why it
  stopped. Laser 4 (2026-10-30) found light at its placeholder but no
  edge, and that pass was lost.

## 0.6.24 - The focus feed test is a timing test

- It counts readings per pass, which follow the host's sleeps: marked
  `sim_timing`, so the loaded Pi skips it as it skips the others.

## 0.6.23 - Lasers 1-3 commissioned across the blades

- `multilbic commission --lasers 1,2,3` with the open side fixed
  (2026-10-30), written to `machine.toml`: the photodiode's corner
  (58.568, 21.016), measured; laser 1 and 3 positions within 70 um of
  the run before; spots 59.4, 39.3 and 30.9 um at the sample's height.
- Tests that read those values follow them.

## 0.6.22 - A steadier focus test

- The test that focus assist follows a moving beam compares as many
  passes up as down, so the reading lag cancels on the slower Pi too.

## 0.6.21 - The open quarter's side, the right way round

- Commissioning and focus assist passed away from the blades, into the
  can's window edge, in A and in B: `open_a`/`open_b` say where the
  open quarter is on the carriage as built, and in the carriage frame
  that is the other way round. `Photodiode.open_signs` turns them now.
  The simulator had the same convention, so it agreed.
- `[photodiode] corner_ab_mm` is an estimate again, (58.44, 21.26),
  `measured = false`: what 0.6.19 wrote was the window's corner. The
  spots written then are that edge's. Commission lasers 1-3 again.
- A pass or an open quarter beyond a laser's reach is a commissioning
  error that says so, not a crash.

## 0.6.20 - Focus assist, from a button in the window

- **Focus...** in the Lasers panel opens focus assist (Phase 6 step 6):
  pick a laser and the edges, Start, and turn the focus while the
  stage passes across the blade's edge on the photodiode. Each pass's
  10-90 % width, the best, and the last five's mean and scatter, with a
  trace. Done measures the laser again; Save writes its position and
  spot into `machine.toml`, and the window carries on with the new file.
- Passes follow the edge as the beam moves and pick their feed for
  about 10 readings across the edge, so about 3 s each at any focus.
- `commission` keeps a measured corner: the laser that moved moves,
  laser 2 too. `--new-corner` when the photodiode itself was moved.
- A calibration loaded into the window, or open while machine.toml
  changes, moves its corner XY with laser 2's position, so the sample
  stays where it is on the carriage. Before, a calibration loaded after
  laser 2 moved would have been off by that much.
- The Cell and Photodiode readings sit one above the other at a fixed
  width: a digit more no longer moves the machine column.

## 0.6.19 - Lasers 1-3 commissioned

- `multilbic commission --lasers 1,2,3` on the machine (2026-10-30),
  written to `machine.toml`: the photodiode's corner (60.239, 23.062),
  now measured; laser 1's and 3's `xy_centre_mm` against laser 2's
  (laser 1 by -0.53, +1.28 mm); spots 238, 272 and 254 um along A.
- Lasers 1 and 2 are out of focus (65 and 41 um on the old stage).
- Tests that assumed an estimated corner or a 41 um spot say so.

## 0.6.18 - X stops at 103

- X's limit is 103, down from 104.5: at 104 the carriage just touches a
  cable (the limit check at the machine, 2026-10-30). A/B checked: about
  1 mm left at 1.0 and 39.0.
- Laser 1 reaches 3.2 mm past the photodiode's corner, enough for
  commissioning's passes (they stop at what each laser can reach).

## 0.6.17 - Wider limits, without recompiling Marlin

- At every connect MultiLBIC turns Marlin's software endstops off
  (`M211 S0`) and sets the A/B home offset (`M206`, `[ab]
  home_offset_mm` = 5): `machine.toml` holds the only limits. After
  every home the driver checks A and B read the offset, and refuses to
  move if not.
- A/B: 0 is the hard stop, limits 0.5-39.5, centre 20 (the full 40 mm,
  0.5 mm clear of each stop). X: to 104.5 (its stop is at 105).
- **Every A/B coordinate is 5 mm more than before** for the same place.
  The photodiode's corner moved with them. Calibrations now record the
  offset, and one made before is refused: calibrate again.
- Laser 1 reaches 4.7 mm past the photodiode's corner (was 0.7).

## 0.6.16 - `multilbic commission`

- Phase 6 step 5: for each laser, the photodiode's open quarter is put
  under it (searching if there is no light), its power read and its
  range chosen, and the two blade edges found with slow passes up and
  down. The corner each laser sees gives its position against the
  reference laser's; the edge widths give the spot. It proposes the
  changes to `machine.toml` and writes them with `--write`
  ([run](docs/run.md)). Simulation only so far.
- `scan.photodiode.reach` takes the room per axis; `span` gives what a
  laser can reach.

## 0.6.15 - The photodiode in the simulator

- `[photodiode]` in `machine.toml`: its channel, where the blades'
  corner is on the carriage (estimated from the bench, not yet
  measured), which quarter is open, the chip's size and the upper
  blade's height. Optional; checked when loaded.
- `scan/photodiode.py`: the X, Y, A and B that put a point on the
  photodiode under a laser, and the room A and B have left. Laser 1
  has 0.7 mm past the corner along A ([hardware](docs/hardware.md)).
- The simulator's channel 2 is the chip under its blades, computed from
  the spot exactly, each edge at its own height and a movable focus;
  it replaces the fixed 40 uA stand-in.

## 0.6.14 - Channel 2's offset went away

- Hardware notes corrected: back on channel 2, the photodiode read like
  channel 1 (laser 1 -739 uA against -733 uA, dark -0.5 nA at -0.3 mV).
  The offset of the afternoon was a state, not channel 2's calibration;
  its cause is unknown (not the cell). Laser 1 is about -735 uA, so the
  afternoon's -466 uA was low.

## 0.6.13 - The three lasers on channel 1

- Hardware notes: with `read --at` on the machine, the photodiode on
  channel 1 reads -733 uA, -6.46 uA and -1.211 mA under lasers 1, 2 and
  3. Laser 3 agrees with channel 2 to 2 % on the same range; lasers 1
  and 2 differ by more, most likely the lasers' own output.

## 0.6.12 - `read` goes to each laser; channel 1 has no offset

- `read --at N=X,Y,A,B`, once per laser: the stage homes, then goes to
  each laser's place before lighting it. Without `--at` nothing moves.
- `read --current-range` per laser (`1=650u,2=25u,3=15m`); a laser on a
  range of its own gets its own dark on that range.
- With the photodiode on channel 1, its dark offsets are about 250 times
  smaller than on channel 2 and it holds its voltage to 0.5 mV: the
  offset is channel 2's ([hardware](docs/hardware.md)).

## 0.6.11 - Channel 2's offset

- Hardware notes: channel 2 reads about 1.7 % of the range's full scale
  high on every range, the same at 0 V and -5 V (+15.9 nA on 1 uA,
  +10.8 uA on 650 uA, +271 uA on 15 mA), and reports its voltage
  +0.27-0.29 V off; channel 1 shows neither. Laser 3 is -1.24 mA on the
  15 mA range; `read`'s autorange "above dark" is high by the lit
  range's offset, so lasers 1 and 2 are about -477 uA and -7.8 uA.

## 0.6.10 - The photodiode in the window; first readings

- The window shows the photodiode (channel 2) beside the cell, read
  together twice a second while idle; it opens the SMU with both
  channels. A reading at autorange's 1 mA limit is marked `(limit)`.
- `read` records the voltage the SMU held with each reading.
- First readings on the photodiode, no motion ([hardware](docs/hardware.md)):
  lasers 1-3 reach the open quarter (A-/B- as built) at positions that
  agree with `machine.toml` to 0.5 mm, so the CAD is the one that is
  off; -466 uA, -7.4 uA and about -1 to -1.24 mA under lasers 1, 2
  and 3; 0 V is fine for laser 1; the 15 mA range reads +271 uA dark.

## 0.6.9 - `read` survives autorange's wild readings

- `multilbic read` summarises by the median and a robust scatter, leaves
  readings far from the median out of the mean (and says how many), and
  keeps every value in its file: on the bench, laser 3 near -0.5 mA gave
  one reading of +6.2 mA among fifty, which made the mean, the scatter
  and both warnings wrong.
- `--current-range` reads on a fixed range, its full scale the current
  limit as in runs, for lasers near the top of autorange's 1 mA limit.

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
  ([hardware](docs/hardware/timing.md#the-serpentine-shift)).
  Laser 3 fits 145 um wide against the 244 um in `machine.toml`.
- Simulator: an SMU that stamps packets late (`Faults.smu_stamp_lag_s`),
  a sample with one straight edge, and `open_sim(sample=)`. On it the
  check recovers an injected 18.6 ms stamp lag and 20 um backlash to
  1.5 ms and 3 um.
- Bench runbook for step 3 in [diagnostics](docs/diagnostics.md#sync-check-the-sync-error-on-one-edge).

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
  ([hardware](docs/hardware/lasers.md#the-laser-supply)).

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
