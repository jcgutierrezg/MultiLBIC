"""
Opening the machine, real or simulated, for the command line and the GUI.

A `Connection` is the three devices plus the clock they run on, and
knows how to close itself. The real machine is opened only while this
process holds the **machine lock**: the operating system's lock on a
file (SMUniversal's `SingleInstance`), so a GUI and a command-line run
can never both drive the ports (D17). The OS drops it when the process
ends, however it ends, so a crash can't leave it stuck. Simulated
machines take no lock: any number of them can run at once.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from multilbic.clock import SYSTEM_CLOCK, Clock, ScaledClock
from multilbic.config.machine import MachineConfig
from multilbic.run.rows import ScanDevices
from multilbic.scan.geometry import Calibration, xy_to_ab

if TYPE_CHECKING:
    from smuniversal_lab_suite.core.single_instance import SingleInstance

    from multilbic.sim.rig import Faults, SimRig

#: Where a simulated machine hides its sample on the carriage, for an
#: operator to find with the photocurrent (`calibrate --sim`, the GUI).
SIM_CORNER_CARRIAGE_MM = (15.2, 16.1)
SIM_SAMPLE_MM = (2.0, 1.0)
#: Simulated seconds per real second, unless asked otherwise.
SIM_SPEED = 5.0


class DeviceSetupError(RuntimeError):
    """The machine can't be opened: no port configured, or the lock is
    held by another process."""


@dataclass
class Connection:
    devices: ScanDevices
    clock: Clock
    simulated: bool
    rig: SimRig | None = None
    lock: SingleInstance | None = None

    def firmware(self) -> dict[str, str | None]:
        d = self.devices
        return {
            "marlin": d.marlin.info.firmware_name if d.marlin.info else None,
            "laser": d.laser.firmware,
            "smu": d.smu.identity,
        }

    def close(self) -> None:
        """Close every device, trying each, then give the lock up."""
        for device in (self.devices.smu, self.devices.laser,
                       self.devices.marlin):
            try:
                device.close()
            except Exception:  # noqa: S110 - best effort on the way out
                pass
        if self.lock is not None:
            self.lock.release()
            self.lock = None


def lock_path() -> Path:
    """MultiLBIC's machine lock, beside SMUniversal's but its own: one
    must not keep the other from starting."""
    from smuniversal_lab_suite.core.single_instance import lock_directory

    return lock_directory().parent / "MultiLBIC" / "machine.lock"


def machine_lock(path: str | Path | None = None) -> SingleInstance:
    """Take the machine lock, or raise `DeviceSetupError`."""
    from smuniversal_lab_suite.core.single_instance import (
        AlreadyRunning,
        SingleInstance,
    )

    lock = SingleInstance(path or lock_path())
    try:
        return lock.acquire()
    except AlreadyRunning:
        raise DeviceSetupError(
            "the machine is in use by another MultiLBIC process (a GUI or "
            f"a command-line run); lock: {lock.path}"
        ) from None


def open_real(
    machine: MachineConfig,
    clock: Clock = SYSTEM_CLOCK,
    *,
    lock_file: str | Path | None = None,
) -> Connection:
    from multilbic.hardware.laser import LaserBoard
    from multilbic.hardware.link import SerialLink
    from multilbic.hardware.marlin import Marlin
    from multilbic.hardware.smu import open_smu

    ports = machine.ports()
    for name in ("skr", "laser", "smu"):
        if not getattr(ports, name):
            raise DeviceSetupError(
                f"no {name} port for {sys.platform} in machine.toml"
            )
    lock = machine_lock(lock_file)
    opened: list = []
    try:
        marlin = Marlin(SerialLink.open(ports.skr, machine.baud, clock),
                        machine, clock)
        opened.append(marlin)
        marlin.open()
        board = LaserBoard(SerialLink.open(ports.laser, machine.baud, clock),
                           machine, clock)
        opened.append(board)
        board.open()
        smu = open_smu(ports.smu, clock)
        opened.append(smu)
        smu.identify()
    except BaseException:
        for device in reversed(opened):
            try:
                device.close()
            except Exception:  # noqa: S110 - already failing
                pass
        lock.release()
        raise
    return Connection(ScanDevices(marlin, board, smu), clock, False,
                      lock=lock)


def open_sim(
    machine: MachineConfig,
    *,
    speed: float = SIM_SPEED,
    corner_carriage_mm: tuple[float, float] = SIM_CORNER_CARRIAGE_MM,
    size_mm: tuple[float, float] = SIM_SAMPLE_MM,
    faults: Faults | None = None,
    clock: Clock | None = None,
) -> Connection:
    """The simulated machine, with a synthetic sample whose corner is
    at `corner_carriage_mm` on the carriage."""
    from multilbic.sim.rig import Faults, SimRig
    from multilbic.sim.sample import SyntheticSample

    clock = clock or ScaledClock(speed, precise=True)
    rig = SimRig(machine, clock, SyntheticSample.default(*size_mm),
                 corner_carriage_mm, faults or Faults())
    rig.open()
    return Connection(ScanDevices(rig.marlin, rig.laser, rig.smu), clock,
                      True, rig=rig)


def sim_corner(
    calibration: Calibration, machine: MachineConfig, faults: Faults
) -> tuple[float, float]:
    """Inverse of `SimRig.perfect_calibration`: where a simulated sample
    really is, given what a perfect operator recorded."""
    half_xy = faults.xy_backlash_mm / 2
    half_ab = faults.backlash_mm / 2
    ref = machine.laser(calibration.reference_laser).xy_centre_mm
    da, db = xy_to_ab(
        calibration.x_along, calibration.y_along,
        calibration.corner_xy_mm[0] - half_xy - ref[0],
        calibration.corner_xy_mm[1] - half_xy - ref[1],
    )
    return (
        calibration.corner_ab_mm[0] - half_ab + da,
        calibration.corner_ab_mm[1] - half_ab + db,
    )
