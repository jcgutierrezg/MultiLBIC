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
