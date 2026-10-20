"""
Bench probes: measurements taken on the machine, one device at a time.

Each probe is a module run with `python -m multilbic.bench.<name>`. It
prints what it finds as it goes and writes everything to one JSON report
under `bench-results/`, stamped with the commit, the version and the
device's firmware. The reports are what Phase 1's numbers come from. The
findings go into `docs/hardware.md`; the JSON files stay out of git.

Every probe also runs with `--sim` against the simulators, which is how
CI makes sure a probe works before it is ever run at the bench. Numbers
from `--sim` describe the simulator, not the machine, and the report
says so.

    python -m multilbic.bench.ports     which serial device is which
    python -m multilbic.bench.marlin    timing, speed, stop behaviour
    python -m multilbic.bench.laser     switching and settle times
    python -m multilbic.bench.smu       stream rate, timestamps, noise
"""
