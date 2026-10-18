"""The same driver checks, against the real machine.

Skipped unless pytest runs with `--hardware`, which happens only on the
Pi. Nothing here moves the stage or homes it: identification, settings,
laser switching and a short stream. The miniSMU's port comes from
`MULTILBIC_SMU_PORT` when machine.toml has none.

    uv run pytest --hardware tests/test_hardware.py
"""

import os

import pytest

from multilbic.clock import SYSTEM_CLOCK
from multilbic.hardware.laser import LaserBoard
from multilbic.hardware.link import SerialLink
from multilbic.hardware.marlin import Marlin
from multilbic.hardware.smu import open_smu

pytestmark = pytest.mark.hardware


@pytest.fixture
def marlin(machine):
    link = SerialLink.open(machine.ports().skr, machine.baud)
    client = Marlin(link, machine, SYSTEM_CLOCK)
    client.open()
    yield client
    client.close()


@pytest.fixture
def laser(machine):
    link = SerialLink.open(machine.ports().laser, machine.baud)
    board = LaserBoard(link, machine, SYSTEM_CLOCK)
    board.open()
    yield board
    board.off()
    board.close()


@pytest.fixture
def smu(machine):
    port = machine.ports().smu or os.environ.get("MULTILBIC_SMU_PORT", "")
    if not port:
        pytest.skip("set MULTILBIC_SMU_PORT or the smu port in machine.toml")
    device = open_smu(port)
    yield device
    device.output_off()
    device.close()


def test_marlin_identifies_as_this_machine(marlin, machine):
    assert marlin.info.machine_type == machine.name
    assert marlin.advanced_ok
    assert marlin.info.capabilities.get("EMERGENCY_PARSER") == "1"


def test_marlin_running_settings_match_machine_toml(marlin, machine):
    # EEPROM can override the compiled values; this says whether it did.
    settings = " ".join(marlin.settings())
    assert f"A{machine.ab.steps_per_mm:.2f}" in settings
    assert f"A{machine.ab.max_feed_mm_s:.2f}" in settings


def test_laser_board_switches(laser):
    laser.select(2)
    assert laser.state().laser == 2
    laser.off()
    assert laser.state().laser == 0


def test_smu_streams(smu):
    smu.identify()
    smu.prepare(bias_v=0.0)
    smu.output_on()
    smu.stream.start(rate_hz=100.0)
    SYSTEM_CLOCK.sleep(2.0)
    stats = smu.stream.stop()
    smu.output_off()
    assert stats.samples.get(1, 0) > 150
    assert stats.parse_errors == 0
