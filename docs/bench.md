---
type: guide
title: "Working on the machine"
---

# Working on the machine

How work reaches the real machine: the Pi over SSH, deploying a branch,
running on it, and bringing results back. Setting the Pi up from
scratch, SSH included, is in [`deploy/pi/`](../deploy/pi/README.md).

## Safety

- **Ask before anything that moves the stage or lights a laser**, and
  have someone at the machine. Readings with no motion and no laser
  (`read` dark, the probes without `--home`/`--lasers`) need neither.
- **Lasers 5 and 6 are infrared and invisible: the box is closed** for
  anything that lights them, and for every map. Focus assist is the one
  job done with the box open, the stage moving only round the blade.
- **One MultiLBIC process has the machine at a time** (the machine
  lock): close the window before a command-line job, and the other way
  round.
- STOP or Esc in the window, Ctrl+C or `kill -INT <pid>` on the command
  line: motion stops at once, lasers and SMU output off, files kept.

## Before a session

- The miniSMU switched on (it has its own switch; off, it is absent from
  USB). If the Pi has just booted, check the laser Xiao is there
  (`python -m multilbic.bench.ports --real`): the boot check usually
  brings it back ([hardware](hardware.md#usb-at-boot)).
- The cell contacted, leads from the top and strain-relieved, the
  photodiode's leads secure, the box over it all, the TFT35 covered.
- Readings of nA on every laser where µA is expected mean the cell's
  contact: reseat the clip, press the cell down
  ([hardware](hardware.md#samples-and-their-contacts)).

## Reaching the Pi

`ssh multilbic` (key login, set up as in
[`deploy/pi/`](../deploy/pi/README.md#ssh)); the Pi is
`multilbic-rpi.local` on the same network. **`sudo` needs a password
that only the operator has**: every `sudo` step is done at the Pi.

### Seeing the Pi's screen

The window runs on the Pi's own monitor. From Windows, GNOME's Desktop
Sharing shows that same screen over Remote Desktop: connect to
`multilbic-rpi.local` with a `.rdp` file that has Network Level
Authentication on (`enablecredsspsupport:i:1`). With automatic login the
GNOME keyring stays locked and Remote Desktop refuses connections until
someone logs in at the Pi.

## Deploying a branch

```bash
ssh multilbic 'bash ~/MultiLBIC/deploy/pi/setup.sh <branch>'
```

It checks out the branch's latest commit, installs Python and the
dependencies, checks serial-port access and Tk's font system, and runs
the tests (the hardware tests and the simulator-timing ones skipped).
**The checkout is a deployment copy, reset to match GitHub: anything
saved into the Pi's `machine.toml` (commissioning, focus, line-up) has
to be copied back and committed first.** While that file has unsaved
changes, git refuses the checkout and the deploy stops there; once its
content is committed, `git checkout -- multilbic/config/machine.toml`
on the Pi lets it through.

A deploy doesn't restart a window that is open: close it and start it
again for the new version.

## Running on the Pi

Long jobs run detached, so a dropped SSH connection doesn't end them:

```bash
ssh multilbic 'cd ~/MultiLBIC && setsid nohup .venv/bin/multilbic run ~/cal/<sample>.json --lasers 1,2,3 --pixel 0.01 --pitch 0.025 --yes > ~/run.log 2>&1 < /dev/null &'
```

Wait on the job's PID or its log, not on `pgrep -f multilbic` (that
matches the watching shell too). Calibration files live in `~/cal`,
runs in `~/multilbic-runs`.

## Testing a laser module

For the new laser board: how each module takes power (a regulator
inside or not, the voltage it needs, light against current), with
`python -m multilbic.bench.laser_module`. The module goes straight onto
the miniSMU's channel 1, the photodiode stays on channel 2, and nothing
else is in the circuit. Its docstring has every stage and limit. About
5 minutes a laser, run **at the Pi's own terminal**: it asks before
lighting, so not under `nohup`.

**The limits are absolute, not today's operating point**, which says
nothing about lasers 1 and 2 on their starved supply. Current is forced
in steps that shrink near the light ceiling, and the sweep stops at the
first of: **5 mW of light** (80 % of it as the power-meter-calibrated
photodiode reads, for margin), the light-against-current curve bending
by 15 % or falling, **5.5 V**, or **120 mA**. A module's own regulator
shows as the voltage jumping to 5.5 V, and ends the sweep too. A facet
can fail before its curve bends: the light ceiling is the guard that
matters. The one thing the probe can't catch is reverse wiring, so
steps 1 and 4 are about polarity.

Once, before any laser:

1. **Which terminal is +**: with nothing on channel 1,
   `python -m multilbic.bench.laser_module --real --polarity-check`
   holds +1.00 V (1 mA limit) until Enter. The terminal the multimeter's
   red probe reads +1.00 V on is channel 1's +.
2. **Dry run on a resistor**: 100 Ω, ½ W, on channel 1, then
   `python -m multilbic.bench.laser_module --real --dummy-load --i-known 20m`.
   It ends with "the limits held" or "THE LIMITS DID NOT HOLD". On the
   second, stop: no laser goes on the instrument.

Each laser (start with laser 4, not the reference laser 3 or the weak
laser 2):

3. **Its power-meter response** (the Maintenance window's Power tab), so
   the light ceiling is in real mW. The probe refuses a laser without
   one unless given `--datasheet-response`, which stops at 65 % instead.
4. **Today's numbers**, on the laser board, the laser lit from the
   window, goggles on:
   - the multimeter in volts across the module's two wires at its
     connector: `--v-known`, and **the wire under the red probe is the
     module's +** (mark it);
   - the multimeter in mA, in series in the + wire: `--i-known`. It is
     only used to check the beam is seen (light by 1.5 x it), not as a
     limit.
5. Laser off. Unplug the module from the laser board and the cell from
   channel 1. Module + to channel 1's +, the other wire to its −, by
   screw terminal or solder, not crocodile clips.
6. In the window, select the laser (it turns the revolver; nothing
   lights) and **Go to photodiode**. Close the window: the probe needs
   the miniSMU. The box closed for lasers 5 and 6.
7. `python -m multilbic.bench.laser_module --real --laser <n> --i-known <mA>m --v-known <V>`
   and type `yes`. It prints what it finds and saves a report and a PNG
   in `bench-results/`.
8. The module back on the laser board, the cell back on channel 1.
   After all the modules, commission all six: handling in the box
   moves lasers ([lasers](hardware/lasers.md)).

A run that stops ("no light by", "did not hold") has switched channel 1
off; its reason is in the report.

## Bringing results back

```bash
scp -r "multilbic:multilbic-runs/<run folder>" runs/
```

```bash
scp "multilbic:MultiLBIC/bench-results/*.json" bench-results/
```

```bash
scp multilbic:MultiLBIC/multilbic/config/machine.toml multilbic/config/machine.toml
```

`runs/` and `bench-results/` are ignored by git; `machine.toml` is
committed. Findings go into [hardware](hardware.md), with the run folder
or report they came from; observations by eye are written there too.
