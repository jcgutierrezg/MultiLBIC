# MultiLBIC

Control software for a multi-wavelength LBIC (laser beam induced current)
mapper. A Raspberry Pi drives a Marlin-controlled XY + AB stage, six
lasers on a servo revolver, and an Undalogic miniSMU that measures the
photocurrent while the sample is rastered under the beam.

**Status: the viewer and spectral response (Phase 7), planned.** The
rewrite runs the machine from the command line and from a window
(`multilbic gui`). All six lasers are commissioned on a reference
photodiode, every map is placed from it, and maps from the six lasers
line up to within a few tens of µm. Next: `multilbic view`, and maps
as EQE.
See [docs/plan.md](docs/plan.md).

| To find | Go to |
|---|---|
| What the machine is: devices, lasers, motion, SMU, photodiode, timing | [docs/hardware.md](docs/hardware.md) |
| How the software is built | [docs/architecture.md](docs/architecture.md) |
| How the software talks to each device; the simulators | [docs/devices.md](docs/devices.md) |
| How a map is made: position, cleaning, the run file | [docs/scan.md](docs/scan.md) |
| Calibrating a sample and running its maps | [docs/run.md](docs/run.md) |
| The window | [docs/gui.md](docs/gui.md) |
| The viewer: a run's maps, from its folder | [docs/viewer.md](docs/viewer.md) |
| Focus, commissioning and the line-up | [docs/commissioning.md](docs/commissioning.md) |
| `read`, `sync-check`, `edges`, the device probes | [docs/diagnostics.md](docs/diagnostics.md) |
| Working on the machine: SSH, deploying, safety | [docs/bench.md](docs/bench.md) |
| Phases and what's next | [docs/plan.md](docs/plan.md) |
| Decisions | [docs/decisions.md](docs/decisions.md) |
| Setting up, running the gates, the workflow | [docs/development.md](docs/development.md) |
| What changed and when | [CHANGELOG.md](CHANGELOG.md) |
| The old scripts | [legacy/](legacy/) |
| Marlin and laser board firmware | [firmware/](firmware/) |
| Pi setup: SSH, install, USB, serials | [deploy/pi/](deploy/pi/) |
