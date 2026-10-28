---
type: guide
title: "Bench sessions"
---

# Bench sessions

How the software gets checked against the real machine: the Pi reached
over SSH, the probes in `multilbic/bench/` run one device at a time,
their JSON reports copied back, and the findings written into
[hardware](hardware.md).

The probes are tested against the simulators in CI
(`tests/test_bench.py`). What is new at the bench is the machine, not
the code.

## Before the first session

**Firmware**

1. *If the updater works,* upgrade the miniSMU to firmware 1.5.0 or
   later, which adds the current range to streamed packets. **Not a
   blocker:** everything runs on 1.4.6, and the probe notes the missing
   field. On 2026-10-19 Undalogic's updater failed with an HTTP 500 from
   their server, so the first session runs on 1.4.6. After a later
   upgrade, re-run the miniSMU probe for a before/after comparison.
   (SMUniversal's bench record for this unit says 1.4.6. Its next
   checkup there will record the new version.)
2. Flash the laser board with
   [`firmware/laser/MultiLBIC_Laser/MultiLBIC_Laser.ino`](../firmware/laser/MultiLBIC_Laser/MultiLBIC_Laser.ino)
   (2.0.0): Arduino IDE, Seeed SAMD boards package, board "Seeeduino
   XIAO". Done 2026-10-19: it compiled as written, and the board
   answers as `MultiLBIC-Laser,2.0.0`.
3. Marlin stays as it is.

**SSH, once**

The Pi runs **Ubuntu 24.04**. The SSH server is not always installed,
and there is no default `pi` user: use the account created when Ubuntu
was installed.

1. On the Pi, install and start the SSH server:
   ```bash
   sudo apt install openssh-server
   ```
   ```bash
   sudo systemctl enable --now ssh
   ```
   **Address the Pi by name, not by IP.** `hostname` prints its name,
   and `<name>.local` finds it on whatever network it is on, as long as
   `avahi-daemon` is running (`systemctl is-active avahi-daemon`; it is
   on Ubuntu Desktop, otherwise `sudo apt install avahi-daemon`).
   `hostname -I` lists IP addresses instead, one for every interface
   (Wi-Fi, Ethernet, IPv6, Docker...), and they change with the network.
   That is why it can show several. Use one only if `.local` fails: the
   IPv4 address on the same network as the PC (compare with `ipconfig`).
2. On Windows, make a key if there isn't one, in PowerShell:
   ```powershell
   ssh-keygen -t ed25519
   ```
   It asks three things:
   - **the file to save the key in:** press Enter for the default,
     `C:\Users\<you>\.ssh\id_ed25519`, which the next steps assume;
   - **a passphrase, then the same again:** press Enter both times to
     leave it empty. Claude connects without a terminal to type a
     passphrase into, so a key with one would lock it out. The trade:
     anyone who can read your Windows user folder could use the key to
     reach the Pi.

   If it says the file already exists, a key is already there. Answer
   `n` and use that one.
3. Copy the public key to the Pi, with your Ubuntu user and the Pi's
   name in place of `<user>@<name>.local`:
   ```powershell
   type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh <user>@<name>.local "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
   ```
   The first connection asks you to confirm the Pi's fingerprint (`yes`),
   then for your Ubuntu password. That is the last time it should ask.
4. Add a short name in `C:\Users\<you>\.ssh\config`:
   ```
   Host multilbic
       HostName <name>.local
       User <user>
   ```
   `ssh multilbic` should now log in without a password, and that is
   how Claude reaches the Pi too.

**Software on the Pi**

git and curl are not always installed on Ubuntu:

```bash
sudo apt install git curl
```

```bash
git clone --branch phase-2-devices https://github.com/jcgutierrezg/MultiLBIC.git ~/MultiLBIC
```

```bash
bash ~/MultiLBIC/deploy/pi/setup.sh phase-2-devices
```

The script exists on a branch before it reaches `main`, so the clone
starts on that branch (a plain clone lands on `main`, without it).

**The first run downloads well over 100 MB** (uv, Python 3.14 and the
packages), so give the Pi a good internet connection for it. A phone
hotspot with poor signal stalled on the first 20 MB. Later runs fetch
only what changed. The bench steps themselves only need the PC and the
Pi on the same network, which a hotspot handles even with weak internet.

After the first run, `bash ~/MultiLBIC/deploy/pi/setup.sh <branch>`
updates the checkout to the branch's latest commit.

**Serial ports on Ubuntu**

Two Ubuntu services interfere with USB serial devices. `setup.sh`
checks for both and prints the fix, but changes neither itself:

- **ModemManager** probes every new `/dev/ttyACM*` device with modem
  commands. The SKR, the laser Xiao and the miniSMU all appear as
  `ttyACM`, so it can hold a port or garble its first seconds. Nothing
  on the Pi needs a modem, so turn it off:
  ```bash
  sudo systemctl disable --now ModemManager
  ```
- **brltty**, the braille display service, claims CH340/CH341 USB-serial
  adapters, and the port disappears. The TFT35's adapter is an FTDI
  (checked 2026-10-19), which it leaves alone, so nothing is needed
  unless a CH340 device is added later:
  ```bash
  sudo apt remove brltty
  ```

`setup.sh` also adds the user to the `dialout` group, which Ubuntu does
not do by default. Log out and back in afterwards (for SSH, reconnect).

**`sudo` needs a password on the Pi, and Claude has none.** Every
`sudo` step (installing curl, the `dialout` group, ModemManager) is
done at the Pi by you, before Claude runs `setup.sh` over SSH. With
those done, `setup.sh` needs no `sudo`.

## A session, in order

Everything runs from `~/MultiLBIC` with `uv run`. Steps marked
**at the machine** move the stage or light a laser. Claude asks before
running any of them, and someone should be watching.

| # | Command | Moves / lights | What it answers |
|---|---|---|---|
| 1 | `python -m multilbic.bench.ports --real` | no | which port and serial number is which board, where the miniSMU is |
| 2 | `pytest --hardware tests/test_hardware.py` | no | do the drivers talk to all three |
| 3 | `python -m multilbic.hardware.check --real --smu-port <port>` | no | the same, with a readable printout |
| 4 | `python -m multilbic.bench.marlin --real` | no | running settings (EEPROM), driver status, command round trip |
| 5 | `python -m multilbic.bench.marlin --real --home --motion` | **at the machine** | real A/B speed, fixed move overhead, how fast Stop acts, keepalive |
| 6 | `python -m multilbic.bench.marlin --real --home --motion --speeds 3,4,5` | **at the machine** | whether A/B can go faster than 2 mm/s; **note what you see and hear at each speed** |
| 7 | `python -m multilbic.bench.laser --real` | no | firmware, angles, settle time |
| 8 | `python -m multilbic.bench.laser --real --lasers` | **at the machine** | switching times; **note whether the servo had stopped before the laser lit, at 2000, 1000 and 500 ms** |
| 9 | `python -m multilbic.bench.smu --real --port <port> --load open` (done 2026-10-19) | no | packet format, achieved stream rates, timestamp resolution, clock drift, open-circuit noise per range |
| 10 | same with the cell contacted: `--load "cell, lights on"`, then `--load "cell, lights off"` | no | the floor with a cell instead of open leads, and the room-light background (DC and 100 Hz flicker) a scan sits on until the enclosure exists |

The miniSMU port comes from step 1. Step 2 also reads it from
`MULTILBIC_SMU_PORT`:

```bash
MULTILBIC_SMU_PORT=/dev/ttyACM2 uv run pytest --hardware tests/test_hardware.py
```

Each probe prints as it goes and writes one report to
`~/MultiLBIC/bench-results/<time>_<probe>_real.json`, stamped with the
commit and firmware. A probe that fails partway still saves what it
had, and a Marlin probe that fails mid-move sends a quickstop first.

## Phase 4: first maps

The first maps off the machine, with the `multilbic` command
([run](run.md)). **Every step here moves the stage and lights a laser**:
someone is at the machine, and Claude asks before starting each one.

`calibrate` is interactive and needs eyes on the spot, so **you** run it
at the Pi (its monitor, or an SSH terminal while standing at the
machine). Claude runs the `run` steps over SSH under `nohup` and copies
the run folders back.

Before: deploy the branch on the Pi (`deploy/pi/setup.sh <branch>`),
replug the Xiao and miniSMU if the Pi has rebooted, contact the cell on
channel 1, cover the TFT35 if its light reaches the sample.

| # | Step | What it answers |
|---|---|---|
| 1 | **Axis directions** (done 2026-10-21: `"+A"`, `"+B"`). `multilbic calibrate --sample axes`; put the spot on a mark near the sample. `a+1`: note which way the mark moves. `a-1`, then `x+1`: if the mark moves the way it did for `a+1`, X is `"+A"`; the opposite way, `"-A"`; across, `"+B"` or `"-B"` (compare with `b+1`). Same for `y+1`. Write `x_along`, `y_along` into `machine.toml` and set `directions_measured = true` | `[geometry]`; until then `run` refuses the machine |
| 2 | **Calibrate the cell.** `multilbic calibrate --sample <name> --out ~/cal/<name>.json`. Corner: the sample's top-right corner as you look at it (the one it extends from towards +A and +B). For a first map, `size 2 2`: a 2 × 2 mm patch from that corner. `trace`, then `save` | the calibration; whether the outline sits on the cell |
| 3 | **Homing repeatability.** `multilbic calibrate --check ~/cal/<name>.json`. Is the spot still on the corner? If not, how far you jog back is the answer | whether `run` homing again keeps calibration valid |
| 4 | (2026-10-21: the first try had the SMU's minus lead off the stage, so a flat map; the second stopped itself after 12 rows when autoranging across 1 µA starved the stream. Runs now fix the range, default 25 µA.) **First map**: `multilbic run ~/cal/<name>.json --lasers 2 --pixel 0.01 --pitch 0.05 --speed 1 --yes` (about 2 min) | a real map; the serpentine shift at 1 mm/s |
| 5 | (2026-10-23, done on the cell's straight right edge instead of the corner patch, which had no edge crossing the rows: +20.5 um at 1 mm/s, +131.9 um at 4 mm/s, an 18.6 ms stamp lag; [hardware](hardware.md#first-maps-2026-10-21-to-2026-10-23).) **Same at 4 mm/s**: `--speed 4` | the shift at 4 mm/s. The shift is `s = b − 2·v·δ` (backlash minus twice speed × latency), so with shifts in µm and speeds in mm/s: latency `δ = (s₁ − s₄) / 6` ms and backlash `b = s₁ + 2δ` µm. `b` goes into `ab_backlash_mm` |
| 6 | (Done 2026-10-23: passed.) **Stop**: step 4 again, `kill -INT` partway | the file says `stopped`, finished rows readable, laser and SMU off |
| 7 | (Done 2026-10-23: lasers 1 and 3 need `--current-range 650u`; offsets and spots in [hardware](hardware.md#first-maps-2026-10-21-to-2026-10-23).) **Three lasers**: `--lasers 1,2,3` on the same patch | how well the maps line up: offsets between them are errors in `xy_centre_mm` (Phase 6 measures them properly) |
| 8 | (Answered by step 5 instead: the shift grows 37 um per mm/s, an 18.6 ms lag, samples stamped after they were measured.) **Stamps** (analysis, no new run): do finger edges in the 4 mm/s map wobble by ~10 µm in step with the 100 ms delivery bursts? | whether the miniSMU stamps packets when it sends them ([hardware](hardware.md#streaming-measured-2026-10-19), *unverified* until now) |

Copy the run folders back:

```bash
scp -r "multilbic:multilbic-runs/*" runs/
```

Findings go into [hardware](hardware.md); `x_along`, `y_along` and
`ab_backlash_mm` into `machine.toml`.

## Phase 5: the window on the Pi

Step 7 of Phase 5: the **simulated** window on the Pi's own monitor.
Nothing moves and no laser lights; the machine's devices stay closed.
It answers what Windows can't: does the window fit the Pi's screen,
does Tk draw it right, does a Pi 4 keep up with a run and its live
map. Claude deploys the branch over SSH; you start the window at the
Pi, from a terminal on its desktop:

```bash
cd ~/MultiLBIC && uv run --no-sync multilbic gui --sim
```

The simulated sample (2 × 1 mm) hides its top-right corner at A 15.2,
B 16.1 with XY under laser 2. Then:

| # | Step | What it answers |
|---|---|---|
| 1 | Look before touching: three columns, nothing cut off at the right or bottom, text readable, the STOP button whole | the layout on the Pi's screen |
| 2 | **Start** (Calibration 1). The stage homes, laser 2 is filled, the photocurrent reads | the worker and readings on the Pi |
| 3 | Click the jog pad, press arrows; then type A 15.2, B 16.1 into Go to, **Go** | keys, moves, the preview's spot |
| 4 | **Set corner here**, width 2, height 1, **Set size**, **Trace the outline** | the calibration steps; the preview zooms to the sample |
| 5 | Run setup: warm-up 0, **Start run**, OK. Watch the live map fill and the time left | whether the Pi keeps up: the window stays responsive, rows appear as they finish |
| 6 | Light/Dark, Console | the theme switch and the console on the Pi's Tk |
| 7 | Start a second run, then close the window with its X | it asks, stops the run, and closes |

2026-10-26: everything worked and fitted, and the window tests passed on
the Pi's desktop, but the text was jagged: uv's Python had a Tk without
Xft. Hence D21 (deadsnakes' Python 3.14, Ubuntu's Tk 8.6): after the
switch the text was smooth, the window worked as before, and all 15
window tests passed on the Pi's display. **Step 7 passed.**

If the simulated run is sluggish, try `--speedup 1` (real time, 5 is
the default): the simulator itself costs CPU, which the real machine
does not.

## Phase 5: a map from the window

Step 9 of Phase 5, the last: the real machine, driven from the window
only. **Steps 2 to 6 move the stage and light lasers**: you are at the
machine and work the window; Claude asks before each step, watches the
run folders and logs over SSH, and copies the runs back.

The target is the test cell's straight right edge, `~/cal/stdtest-redge.json`
(2 × 2 mm, used on 2026-10-23). Its command-line maps at 1 mm/s gave a
+20.5 um serpentine shift (+19.6 um from the alignment), so a map from
the window has numbers to agree with.

Before: the Pi on the branch (`deploy/pi/setup.sh phase-5-gui`, fonts
smooth); replug the Xiao and the miniSMU if the Pi has rebooted; the
cell contacted with the leads from the top (the backplate clip gave
flat maps); the box over it; no `multilbic` process running.

```bash
cd ~/MultiLBIC && uv run --no-sync multilbic gui
```

| # | Step | What it answers |
|---|---|---|
| 1 | **Connect** (no motion). Three green lamps with firmware; if one is red, replug it and Connect again. Claude then tries `multilbic run` over SSH: it must stop with "the machine is in use" | the real devices through the worker; the machine lock (D17) |
| 2 | **Start** (homes; laser 2 on over the AB centre), **Load...** `stdtest-redge.json`, **Go to corner**. Is the spot on the corner? If not, jog onto it (click the pad: the arrows must move the spot on the cell the way they point) and **Set corner here**. **Trace the outline**, then **Save...** as `~/cal/stdtest-gui.json` | homing repeatability as Phase 4 step 3 did; the jog arrows on the real cell (D19 and `[display]`); the drawing's spot following the real stage |
| 3 | **A map**: laser 2, pixel 0.01, pitch 0.05, speed **1**, range 25u, baseline 3, warm-up 60 (the default). **Start run**, check the dialog, OK. About 3 min. Watch the warm-up, the time left, the live map filling, then the finished map replacing it | a real run from the window; whether its map, and the shift it reports, agree with the command line's on the same edge (Claude compares the files) |
| 4 | **STOP mid-row**: step 3 again with warm-up 0; press STOP after a few rows | as Phase 4 step 6, from the button: the file says `stopped` with its finished rows, laser and SMU off, stage still; Home works afterwards |
| 5 | **Esc mid-row**: the same, with Esc | the key does what the button does |
| 6 | **Closing mid-run**: step 3 again with warm-up 0; close the window with its X, answer Yes | it asks, stops the run, makes everything safe, then closes; a new window connects at once (the lock is released) |

Pass: steps 1-6 as described, and step 3's map matches the command
line's (the edge in the same place within the spot size, the shift
within a few um of +20). Then Phase 5 is done and the branch gets its
PR. Findings go into [hardware](hardware.md); anything the window got
wrong into the plan.

Copy the run folders back:

```bash
scp -r "multilbic:multilbic-runs/*" runs/
```

**Done 2026-10-26 and 27: steps 1-6 passed** (runs `20261026T173940Z`,
`20261026T174747Z`, `20261027T120706Z`, `20261027T121004Z`; findings in
[hardware](hardware.md#a-map-from-the-window-2026-10-26-and-27)).

1. Three green lamps; a second process was refused the lock. (Checked
   by taking the lock directly from SSH rather than with `multilbic
   run`: had the lock been free, `run --yes` would have moved the stage.)
2. Homing, loading, the trace and saving worked; the arrows moved the
   spot on the cell the way they point. **Runbook flaw:** this
   calibration's corner is beside the cell, not a feature, so "is the
   spot on the corner?" can't be seen. The operator found the cell's
   real top-right corner instead, at A 17.6, B 17.4 with XY unchanged:
   0.1 mm each way from `stdtest1` (2026-10-21). For a homing check, use
   a calibration whose corner is a feature.
3. Complete in 3 min 40 s. The window ran it as the command line does:
   each row took 2.3158 s from sent to finished against 2.3160 s on
   2026-10-23, same spread, so the window's redraws delayed nothing.
   Shift from the edge, row against neighbouring row: +23 um (the
   reference +17 to +20 um). **Not met:** the edge sits 0.2 mm further
   into the patch than on 2026-10-23, is much sharper, and bows by about
   0.1 mm. Laser 2 was refocused by eye after the reference run (spot
   about 0.2 mm then, 41 um after), which sharpens the edge and can move
   the spot sideways; the corner check found 0.1 mm of it. Not the
   window's doing, and only the photodiode (Phase 6) can say how much
   is the laser. Also: the map's own alignment gave +9.4 um against
   +23 um from the edge (on the reference both said ~20).
4. STOP during row 6: the file says `stopped` with 5 rows and a map,
   laser off, stage stopped at once; Home worked after.
5. Esc during row 7: the same, 6 rows.
6. Closing during row 7: it asked, stopped the run (6 rows, `stopped`),
   closed; the lock was free; a new window connected at once.

## Current ranges: the bench

Ranges step 6 ([plan](plan.md#current-ranges-per-sample)), on the test
cell, from the window, with `stdtest-gui.json` loaded (the 2 x 2 mm
patch on the cell's right edge).

| # | Step | What it answers |
|---|---|---|
| 1 | Tick lasers 1-3, **Check ranges**, Yes. Read the log in **Console**: one line per grid line, with its readings | each laser's range on this sample: expect 650u, 25u, 650u |
| 2 | **Save...**, then **Start run** with lasers 1-3 on the checked ranges | a mixed-range run completes with no clip; each file and `run.json` record the laser's range and limit |
| 3 | Laser 1 alone, its range set by hand to **25u**, **Start run** | the step-up: the 25u attempt is kept and marked clipped, the laser starts again on 650u and completes |

**Done 2026-10-27: all three passed** (runs `20261027T175902Z`,
`20261027T181352Z`; findings in
[hardware](hardware.md#current-ranges-on-the-test-cell-2026-10-27)).

0. The first check (0.5.21, 17:31) read 1-12 nA on every laser and
   chose 1u for all three. The same calibration's grid read 2-93 uA an
   hour later. In that session the window's own photocurrent readout
   also read 140 pA dark and -1 nA lit, against -13 nA and -40 nA from
   a script on the same spot. So the SMU was not sourcing into the cell
   then (output, or contact); the code does the same thing in both
   sessions. A no-motion script showed single readings agree with the
   stream (-37 to -47 nA against -46 nA) and laser 2's light on the
   cell within 0.25 s of selecting it. 0.5.22 turns each laser on
   before its travel and logs every grid line.
1. Peaks 24 uA, 2.3 uA, 92.7 uA: **650u, 25u, 650u**, as expected.
   Lines near the cell's edge read hundreds of nA, the rest uA.
2. Complete in 6 min 32 s (the Plan tab said 6 min 51 s). No clip.
   Headers: range and current limit 650u / 25u / 650u. The SMU took
   the 25 uA limit, the first time below 1 mA. Peaks in the maps:
   96.9 uA, 3.06 uA, 118 uA, each well inside its range.
3. Row 0 clipped at 26.8 uA, 81 s after the laser started (60 s
   warm-up, baseline, then the row). `laser1_444nm_25u.csv` says
   `clipped: row 0: 26.8 uA reaches the end of the 25 uA range`; the
   laser started again on 650u with no second warm-up and completed
   49 s later. `run.json` lists the clipped attempt; the map matches
   step 2's.

Afterwards (2026-10-27 and 28), finding why the check under-read laser
1 ([hardware](hardware.md#current-ranges-on-the-test-cell-2026-10-27)):
not warm-up, not autorange, but laser 1 relit within ~1.5 s of going
off (0.5.25 keeps a laser dark 3 s first). Rechecked on 0.5.25:
**laser 1 80 uA (650u), laser 2 0.31 uA (1u), laser 3 91.9 uA (650u)**.
The check before it, the first after homing, read nA on every laser:
the crocodile-clip contact, which homing can disturb.

## Phase 6: the sync check

Phase 6 step 3 ([plan](plan.md#phase-6-commissioning)), on the test
cell's straight right edge, no photodiode. **It moves the stage and
lights laser 2**: someone is at the machine, and Claude asks before
starting. Claude runs it over SSH under `nohup` (`setsid nohup ...
< /dev/null`), as with `run`.

Before: deploy the branch on the Pi, replug the Xiao and miniSMU if the
Pi rebooted, check the clips (nA on every laser means the clips), the
cardboard box over the cell.

| # | Step | What it answers |
|---|---|---|
| 1 | **Where the edge is now.** `multilbic run ~/cal/stdtest-redge.json --lasers 2 --pixel 0.01 --pitch 0.1 --speed 4 --yes`, then `multilbic edges` on its file | the edge's `u` along the patch, for the window; laser 2's current range |
| 2 | **The sync check.** `multilbic sync-check ~/cal/stdtest-redge.json --laser 2 --window <u-0.4>,<u+0.4>,0.5,1.5 --speeds 1,4,5 --yes` (about 20 min) | `L` and the A backlash separately; the alignment against the edges at 1, 4 and 5 mm/s; the drift over the session; laser 2's spot |
| 3 | **Option C**, by reading step 2: is the spread of the per-row offsets (the stamp bunching) small against the pixel sizes maps use? | whether a hardware marker is needed |

The result goes into [hardware](hardware.md); `L` and the backlash
decide whether `ab_backlash_mm` changes and whether 5 mm/s becomes the
default (D27).

## Afterwards

Copy the reports back:

```bash
scp "multilbic:MultiLBIC/bench-results/*.json" bench-results/
```

Findings go into [hardware](hardware.md), replacing *unverified* marks
with measured values and the report they came from. The JSON files
themselves stay out of git (`bench-results/` is ignored), and so do
observations by eye, which are recorded in the docs alongside the
numbers.

Decisions these numbers feed:

- the stream rate and the A/B scan speed (sync budget, run times);
- the current range for scans (autorange glitches against fixed-range
  resolution at the floor measured with a cell connected);
- the laser settle time;
- whether `machine.toml` needs the miniSMU port, or a lookup by USB
  serial number instead of udev names.
