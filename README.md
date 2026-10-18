# MultiLBIC

Control software for a multi-wavelength LBIC (laser beam induced current)
mapper. A Raspberry Pi drives a Marlin-controlled XY + AB stage, six
lasers on a servo revolver, and an Undalogic miniSMU that measures the
photocurrent while the sample is rastered under the beam.

**Status: being rewritten.** The plan is agreed before code; nothing in
the new structure exists yet.

| To find | Go to |
|---|---|
| What the machine is: devices, firmware, known values | [docs/hardware.md](docs/hardware.md) |
| How the software is meant to be built | [docs/architecture.md](docs/architecture.md) |
| Phases, what's next, decisions | [docs/plan.md](docs/plan.md) |
| What changed and when | [CHANGELOG.md](CHANGELOG.md) |
| The old scripts | [legacy/](legacy/) |
| Marlin and laser board firmware | [firmware/](firmware/) |
| Pi setup (udev, serials) | [deploy/pi/](deploy/pi/) |
