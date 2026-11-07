---
type: state
title: "Decisions"
---

# Decisions

Agreed decisions, numbered in the order they were taken. A revised
decision keeps its number and says what it was.

| # | Decision | Agreed |
|---|---|---|
| D1 | When the run file is written | After every completed row; Stop keeps the partial data (unlike SMUniversal rules 3 and 7). |
| D2 | Stream rate | Derived from the pixel size and speed: 2 samples a pixel, kept within 400–1000 Hz. Compression waits for real files. |
| D3 | Row order | Serpentine by default, one direction as an option. |
| D4 | Versions | MAJOR.SESSION.PUSH from 0.1.0; from Phase 4 on the middle number is the phase. |
| D5 | Channel-2 photodiode | On an AB corner, outside the sample area ([architecture](architecture.md#the-channel-2-reference-photodiode)). |
| D6 | Reaching the window on the Pi | Built and tested against the simulator on Windows; on the Pi it runs on the Pi's own monitor. **Since 2026-11-03** that screen can be shared to Windows over GNOME Remote Desktop ([bench](bench.md#seeing-the-pis-screen)); no X forwarding. |
| D7 | SMUniversal dependency | Pinned git dependency, installing only what the miniSMU needs. |
| D8 | Separating LBIC signal from slow drift | Open, **set aside** (2026-10-20): dark noise is mostly 0.2–0.7 Hz drift, the band a map's features pass in. (a) a stable dark enclosure and laser-off baselines; (b) chopping the laser and demodulating in software (the miniSMU tops out near 1.4 kHz). Maps do mains removal and a dark baseline per laser; drift stays in. |
| D9 | A/B speed ceiling | **5 mm/s** (2026-11-04; was 6, the EEPROM's): over the whole travel, 6 mm/s vibrates on A and struggles on B. Sent as `M203` at every connect. |
| D10 | Laser settle time | **2000 ms** (`[laser_board] settle_ms`), set at every `open()`: 1000 ms was steady on the worst swing, 500 ms was not. |
| D11 | Where the sample is | XY-based: the corner is jogged under the reference laser with AB centred; for each laser XY centres the sample and AB rasters round the AB centre. Every placing move ends moving up. |
| D12 | Corner calibration | One corner (the one the sample extends from towards +A and +B), the size typed, the laser tracing the outline to check it. |
| D13 | Command line | `multilbic calibrate` (interactive, saves a file) and `multilbic run` (reads it, needs no terminal). `run` homes first. Ctrl+C or SIGINT/SIGTERM is Stop. No resume within a laser. |
| D14 | Lasers whose position isn't measured | Refused by `run` unless `--allow-unmeasured`. |
| D15 | SMU range during scans | Fixed for each laser's whole map: autoranging drops 10–15 ms of samples at every switch. **Revised 2026-10-27**: per laser and per sample (D25, D26). |
| D16 | Laser warm-up | Each laser on with the stage still for `--warmup` (60 s) before its first row, recorded in the file. |
| D17 | Where a window's run lives | In the window's process, on the worker thread. A crash stops the run as Stop does and keeps the file; a run that must outlive the window is `multilbic run` under `nohup`. The machine lock keeps two processes off the ports. |
| D18 | The live map | Binned row by row, **without** the serpentine correction; the corrected map, built from the file, replaces it when each laser ends. |
| D19 | Jog keys | Arrows and `w a s d q e`, only while the jog pad has focus. **Revised 2026-10-28**: the arrows move the stage the way they point. |
| D20 | Start | A confirm dialog with the lasers, the plan and the estimate. |
| D21 | Python on the Pi | **Deadsnakes' `python3.14` + `python3.14-tk`**, with Ubuntu's Tk 8.6, whose text is smooth; uv's 3.14 has a Tk without Xft. `setup.sh` prefers it and falls back with a warning. |
| D22 | Where commissioning lives | A command, `multilbic commission`, and the window, on the same Tk-free code. In the window it is the Maintenance window's tabs (D28). |
| D23 | Where commissioning results go | Into `machine.toml`, shown first and written only on the operator's yes; each session's readings to a file in the runs folder. |
| D24 | Focus | A hand adjustment at the laser; the software measures the spot on the blade pass after pass and shows whether it is getting sharper. No motorised focus. |
| D25 | Where a sample's ranges come from | **Measured at calibration and saved with it**: a coarse grid under each laser on autorange, the smallest range holding 3× the brightest reading. The SMU's current limit follows the range; all five ranges. |
| D26 | A range that clips during a run | **Step up and start that laser's map again**, keeping the clipped attempt; clipping at 180 mA fails the run. On by default. |
| D27 | Default scan speed | **4 mm/s** (was 2). The sync check (2026-11-04) kept it: rows scatter more at 5. |
| D28 | The reference laser, and each laser's offset on the cell | **Laser 3** (2026-11-05; was 2, too weak on its supply). Calibrations made under laser 2 stay right: each records its reference laser's position. Each laser gets a `cell_offset_xy_mm` from the line-up against laser 3. Focus, commissioning and the line-up live in a Maintenance window, so none needs the command line. |
| D29 | Placing each laser | **From the photodiode at every run** (0.6.43): the servo lands a laser differently each selection. The servo is released after each turn (firmware 2.1.0, 0.6.44). |
| D30 | The viewer | **Its own window, `multilbic view`** (2026-11-06), on the PC and the Pi: no devices, no lock. Folders are copied from the Pi by hand. First version: one map explored, the lasers compared, EQE and the spectrum; exports later. **Revised 2026-11-07**: it reads run folders and writes into them only each laser's alignment file (`laser<N>_<nm>nm.align.json`), which the run writes too, so a map opens without searching for its alignment again; **Re-align** searches again, **Set shift** saves one typed by hand ([scan](scan.md#the-alignment-beside-it)). |
| D31 | Laser power for each map | **Read on the photodiode before and after each map** (2026-11-06): the laser warms up on the photodiode where it was located, the end of the warm-up is the power before; the stage goes back for the power after. EQE uses the power interpolated linearly in time, row by row. |
| D32 | What a normalised map shows | **EQE**, from the S1223-01's typical datasheet responsivity at each laser's wavelength, labelled as such (2026-11-06). A calibrated photodiode later changes only the curve. |
| D33 | Option C, the hardware row marker | **Dropped** (2026-11-06): dated by count, maps agree with their own edges to 2–3 µm ([timing](hardware/timing.md#the-sync-check)). The design stays in [architecture](architecture.md#option-c-hardware-marker-dropped). |
