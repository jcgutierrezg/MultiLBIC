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
   Note the address with `hostname -I`. `<hostname>.local` also works
   if `avahi-daemon` is running, which it is on Ubuntu Desktop.
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
   address in place of `<user>@<address>`:
   ```powershell
   type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh <user>@<address> "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
   ```
4. Add a short name in `C:\Users\<you>\.ssh\config`:
   ```
   Host multilbic
       HostName <address>
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
git clone https://github.com/jcgutierrezg/MultiLBIC.git ~/MultiLBIC
```

```bash
bash ~/MultiLBIC/deploy/pi/setup.sh phase-2-devices
```

The script exists on a branch before it reaches `main`, so it is run
from the clone rather than downloaded.

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
  adapters, and the port disappears. If the TFT35's adapter is one (step
  1 below says), and nothing on the Pi uses a braille display:
  ```bash
  sudo apt remove brltty
  ```

`setup.sh` also adds the user to the `dialout` group, which Ubuntu does
not do by default. Log out and back in afterwards (for SSH, reconnect).

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
