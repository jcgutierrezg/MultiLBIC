# MultiLBIC

Control software for a multi-wavelength LBIC (laser beam induced current)
mapper. A Raspberry Pi drives a Marlin-controlled XY + AB stage, six
lasers on a servo revolver, and an Undalogic miniSMU that measures the
photocurrent while the sample is rastered under the beam.

**Status: being rewritten.** Project foundations, the device layer
(drivers + simulators) and the scan core are in place, the last in
simulation only; running a whole map on the machine comes next. See
[docs/plan.md](docs/plan.md).

| To find | Go to |
|---|---|
| What the machine is: devices, firmware, known values | [docs/hardware.md](docs/hardware.md) |
| How the software is meant to be built | [docs/architecture.md](docs/architecture.md) |
| How the software talks to each device; the simulators | [docs/devices.md](docs/devices.md) |
| How a map is made: position sync, cleaning, the run file | [docs/scan.md](docs/scan.md) |
| Phases, what's next, decisions | [docs/plan.md](docs/plan.md) |
| Setting up, running the gates, the workflow | [docs/development.md](docs/development.md) |
| Running the probes on the machine over SSH | [docs/bench.md](docs/bench.md) |
| What changed and when | [CHANGELOG.md](CHANGELOG.md) |
| The old scripts | [legacy/](legacy/) |
| Marlin and laser board firmware | [firmware/](firmware/) |
| Pi setup (udev, serials) | [deploy/pi/](deploy/pi/) |
