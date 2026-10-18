"""The laser board driver, against the simulated 2.0.0 firmware."""

import pytest

from multilbic.hardware.laser import LaserBoard, LaserBoardError
from multilbic.sim.fake_laser import FakeLaserBoard
from multilbic.sim.link import connect


@pytest.fixture
def rig(machine, clock):
    fake = FakeLaserBoard()
    board = LaserBoard(connect(fake, clock), machine, clock)
    board.open()
    yield board, fake, clock
    board.close()


def test_open_identifies_and_reads_settle(rig):
    board, _, _ = rig
    assert board.firmware == "MultiLBIC-Laser,2.0.0"
    assert board.settle_ms == 2000


def test_open_refuses_other_firmware(machine, clock):
    fake = FakeLaserBoard(firmware_id="Servo moved to: 90")
    board = LaserBoard(connect(fake, clock), machine, clock)
    with pytest.raises(LaserBoardError, match="not a MultiLBIC laser"):
        board.open()


def test_open_refuses_mismatched_angles(machine, clock):
    fake = FakeLaserBoard(angles=(150, 90, 30, 150, 90, 45))
    board = LaserBoard(connect(fake, clock), machine, clock)
    with pytest.raises(LaserBoardError, match="do not match"):
        board.open()


def test_select_and_off(rig):
    board, fake, _ = rig
    board.select(3)
    assert board.state().laser == 3
    assert board.state().servo_angle_deg == 30
    assert fake.active == 3
    board.off()
    assert board.state().laser == 0
    # LASER 0 no longer parks the servo.
    assert board.state().servo_angle_deg == 30


def test_settle_skipped_when_angle_unchanged(rig):
    board, _, clock = rig
    board.select(1)  # 90 -> 150: settles
    start = clock.now()
    board.select(4)  # also 150: no servo move, no settle
    assert clock.now() - start < 0.5
    start = clock.now()
    board.select(2)  # 150 -> 90: settles
    assert clock.now() - start == pytest.approx(2.0, abs=0.3)


def test_set_settle(rig):
    board, _, clock = rig
    board.set_settle(500)
    start = clock.now()
    board.select(3)
    assert clock.now() - start == pytest.approx(0.5, abs=0.2)


def test_refusals(rig):
    board, _, _ = rig
    with pytest.raises(LaserBoardError, match="BAD_VALUE"):
        board.set_settle(20000)
    with pytest.raises(LaserBoardError, match="BAD_LASER"):
        board.query("LASER 9")
    with pytest.raises(KeyError):
        board.select(7)  # refused before anything is sent


def test_timeout_puts_the_link_out_of_step(rig):
    board, fake, _ = rig
    fake.silent = True
    with pytest.raises(LaserBoardError, match="no reply"):
        board.state()
    with pytest.raises(LaserBoardError, match="resync"):
        board.state()
    fake.silent = False
    board.resync()
    assert board.state().laser == 0
