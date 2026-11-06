"""Shared fixtures, the switch that keeps hardware tests off by default,
and the test windows kept off the screen.

Tests marked `hardware` need the real machine. They are skipped unless
pytest is run with `--hardware`, which is only ever done on the Pi.
"""

import os

import pytest

from multilbic.clock import ScaledClock
from multilbic.config import load

#: Simulated seconds per real second in device tests. At 100 a Windows
#: CI runner once stalled the fake Marlin's thread for over 40 ms real,
#: which is 4 s simulated, and a 5 s timeout fired (2026-10-20). At 20 a
#: 5 s timeout is 250 ms of real time and 1 ms of scheduling jitter is
#: 20 ms simulated; a 15 s simulated row still takes only 0.75 s.
SIM_SPEED = 20.0


def pytest_addoption(parser):
    parser.addoption(
        "--hardware",
        action="store_true",
        help="run tests that need the real MultiLBIC machine",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--hardware"):
        return
    skip = pytest.mark.skip(reason="needs the machine: run with --hardware")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session", autouse=True)
def _keep_test_windows_off_screen():
    """Build every test window transparent and off-screen, as
    SMUniversal's suite does.

    The window tests build real windows, which used to appear on top of
    whatever the person running the suite was doing (the builder asked,
    2026-11-03). Windows has no virtual display to put them on, so they
    are made invisible instead: fully transparent, and far outside the
    desktop. They are still real, mapped windows, so geometry, events
    and `update()` behave as before.

    Set `MULTILBIC_TEST_SHOW_WINDOWS=1` to see them (to watch a test, or
    take a screenshot of one).
    """
    if os.environ.get("MULTILBIC_TEST_SHOW_WINDOWS"):
        yield
        return
    try:
        import tkinter as tk
    except ImportError:
        yield
        return
    originals = {cls: cls.__init__ for cls in (tk.Tk, tk.Toplevel)}

    def hiding(original):
        def init(self, *args, **kwargs):
            original(self, *args, **kwargs)
            try:
                self.attributes("-alpha", 0.0)
                self.geometry("+-32000+-32000")
            except tk.TclError:
                pass  # a platform without alpha still runs the test
        return init

    for cls, original in originals.items():
        cls.__init__ = hiding(original)
    yield
    for cls, original in originals.items():
        cls.__init__ = original


@pytest.fixture
def machine():
    return load()


@pytest.fixture
def clock():
    return ScaledClock(SIM_SPEED)


@pytest.fixture(scope="session")
def run_folder(tmp_path_factory):
    """A finished two-laser run on the simulator, made once for the whole
    session: the run folder tests and the viewer's open it."""
    from multilbic.run.rows import ScanDevices
    from multilbic.run.session import RunRequest, Session
    from multilbic.sim.rig import Faults, SimRig
    from multilbic.sim.sample import SyntheticSample
    from multilbic.sim.scan import sim_machine

    clock = ScaledClock(SIM_SPEED)
    faults = Faults()
    machine = sim_machine(load(), faults)
    rig = SimRig(machine, clock, SyntheticSample.default(0.3, 0.15),
                 (15.0, 16.0), faults)
    rig.open()
    try:
        request = RunRequest(
            rig.perfect_calibration("two lasers"), (1, 2),
            pixel_mm=0.01, pitch_mm=0.05, speed_mm_s=2.0,
            baseline_s=0.5, warmup_s=0.0, note="runfolder test")
        session = Session(ScanDevices(rig.marlin, rig.laser, rig.smu),
                          machine, clock, request,
                          tmp_path_factory.mktemp("runs"), simulated=True,
                          provenance={"commit": "test"})
        outcome = session.run()
    finally:
        rig.close()
    assert outcome.status == "complete"
    return outcome.folder
