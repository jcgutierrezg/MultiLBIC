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
