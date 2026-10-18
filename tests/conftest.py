"""Shared fixtures, and the switch that keeps hardware tests off by default.

Tests marked `hardware` need the real machine. They are skipped unless
pytest is run with `--hardware`, which is only ever done on the Pi.
"""

import pytest

from multilbic.clock import ScaledClock
from multilbic.config import load

#: Simulated seconds per real second in device tests. High enough that a
#: 15 s simulated row takes 0.15 s; low enough that thread scheduling
#: jitter (~1 ms real) stays ~0.1 s simulated.
SIM_SPEED = 100.0


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
