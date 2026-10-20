"""Shared fixtures, and the switch that keeps hardware tests off by default.

Tests marked `hardware` need the real machine. They are skipped unless
pytest is run with `--hardware`, which is only ever done on the Pi.
"""

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


@pytest.fixture
def machine():
    return load()


@pytest.fixture
def clock():
    return ScaledClock(SIM_SPEED)
