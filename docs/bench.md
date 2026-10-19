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

1. Upgrade the miniSMU to firmware 1.5.0 or later, which adds the
   current range to streamed packets. (SMUniversal's bench record for
   this unit says 1.4.6. Its next checkup there will record the new
   version.)
2. Flash the laser board with
   [`firmware/laser/MultiLBIC_Laser/MultiLBIC_Laser.ino`](../firmware/laser/MultiLBIC_Laser/MultiLBIC_Laser.ino)
   (2.0.0): Arduino IDE, Seeed SAMD boards package, board "Seeeduino
   XIAO". Not compiled anywhere yet, so the first build may need a fix.
3. Marlin stays as it is.

**SSH, once**

1. On the Pi, enable SSH (`sudo raspi-config` → Interface Options → SSH)
   and note the address (`hostname -I`, or `<hostname>.local`).
2. On Windows, make a key if there isn't one, in PowerShell:
   ```powershell
   ssh-keygen -t ed25519
   ```
3. Copy the public key to the Pi (replace `pi@raspberrypi.local` with
   the real user and address):
   ```powershell
   type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh pi@raspberrypi.local "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
   ```
4. Add a short name in `C:\Users\<you>\.ssh\config`:
   ```
   Host multilbic
       HostName raspberrypi.local
       User pi
   ```
   `ssh multilbic` should now log in without a password, and that is
   how Claude reaches the Pi too.

**Software on the Pi**

```bash
git clone https://github.com/jcgutierrezg/MultiLBIC.git ~/MultiLBIC
```

```bash
bash ~/MultiLBIC/deploy/pi/setup.sh phase-2-devices
```

The script exists on a branch before it reaches `main`, so it is run
from the clone rather than downloaded.

After the first run, `bash ~/MultiLBIC/deploy/pi/setup.sh <branch>`
updates the checkout to the branch's latest commit.

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
| 9 | `python -m multilbic.bench.smu --real --port <port> --load open` | no | packet format, achieved stream rates, timestamp resolution, clock drift, open-circuit noise per range |
| 10 | same with `--load dark-cell` | no | the noise floor with a covered cell connected: what an LBIC signal has to clear |

The miniSMU port comes from step 1. Step 2 also reads it from
`MULTILBIC_SMU_PORT`:

```bash
MULTILBIC_SMU_PORT=/dev/ttyACM2 uv run pytest --hardware tests/test_hardware.py
```

Each probe prints as it goes and writes one report to
`~/MultiLBIC/bench-results/<time>_<probe>_real.json`, stamped with the
commit and firmware. A probe that fails partway still saves what it
had, and a Marlin probe that fails mid-move sends a quickstop first.

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
  resolution at the dark-cell floor);
- the laser settle time;
- whether `machine.toml` needs the miniSMU port, or a lookup by USB
  serial number instead of udev names.
