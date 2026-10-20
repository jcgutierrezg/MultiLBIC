"""
Check every device answers, on the machine or in simulation.

    uv run python -m multilbic.hardware.check --sim
    uv run python -m multilbic.hardware.check --real --smu-port /dev/ttyACM2

On the machine it is careful by default: it identifies each device,
reads positions and settings, streams two seconds from the miniSMU, and
turns the lasers off. Motion and lasers only with explicit flags:

    --home     home all axes (sensorless: drives each axis into its stop)
    --move     after homing, move AB to its centre and trace a 1 mm square
    --lasers   light each laser in turn, then off

Exit status is non-zero if any device failed.
"""

from __future__ import annotations

import argparse
import contextlib
import statistics
import sys
import traceback

from multilbic.clock import SYSTEM_CLOCK, Clock, ScaledClock
from multilbic.config import load
from multilbic.config.machine import MachineConfig
from multilbic.hardware.laser import LaserBoard
from multilbic.hardware.link import SerialLink
from multilbic.hardware.marlin import Marlin
from multilbic.hardware.smu import PhotocurrentSmu, open_smu

AB_CHECK_FEED_MM_S = 1.0


def _say(text: str) -> None:
    print(text, flush=True)


def check_marlin(marlin: Marlin, machine: MachineConfig, args) -> None:
    info = marlin.open()
    _say(f"  firmware: {info.firmware_name}")
    _say(f"  machine:  {info.machine_type}, ADVANCED_OK {marlin.advanced_ok}")
    for line in marlin.settings():
        if any(code in line for code in ("M92", "M203", "M201", "M425")):
            _say(f"  {line.removeprefix('echo:').strip()}")
    _say(f"  position: {marlin.position()}")
    if args.home:
        _say("  homing...")
        marlin.home()
        _say(f"  homed at: {marlin.position()}")
    if args.move:
        if not marlin.position_trusted:
            raise RuntimeError("--move needs --home")
        a0, b0 = machine.ab.centre_mm
        feed = AB_CHECK_FEED_MM_S
        marlin.move_to(a=a0, b=b0, feed_mm_s=feed)
        for da, db in ((1, 0), (1, 1), (0, 1), (0, 0)):
            marlin.move_to(a=a0 + da, b=b0 + db, feed_mm_s=feed)
        marlin.wait_idle(timeout=10.0)
        _say(f"  square done at: {marlin.position()}")


def check_laser(board: LaserBoard, machine: MachineConfig, args) -> None:
    _say(f"  firmware: {board.open()}, settle {board.settle_ms} ms")
    _say(f"  state:    {board.state()}")
    if args.lasers:
        for laser in machine.lasers:
            board.select(laser.number)
            _say(f"  laser {laser.number} ({laser.wavelength_nm} nm) on")
    board.off()
    _say(f"  off:      {board.state()}")


def check_smu(smu: PhotocurrentSmu, args) -> None:
    _say(f"  identity: {smu.identify()}")
    if not smu.firmware_streams_range:
        _say("  note: firmware below 1.5.0, packets carry no current range")
    smu.prepare(bias_v=0.0)
    smu.output_on()
    try:
        smu.stream.start(channels=(1,), rate_hz=args.rate)
        args.clock.sleep(2.0)
        stats = smu.stream.stop()
    finally:
        smu.output_off()
    samples = smu.stream.drain()
    currents = [s.current_a for s in samples]
    _say(
        f"  streamed: {stats.samples.get(1, 0)} samples, achieved "
        f"{stats.rate_hz(1) or 0:.1f} Hz of {args.rate:.0f}, "
        f"{stats.parse_errors} parse errors"
    )
    if len(currents) > 1:
        _say(
            f"  current:  mean {statistics.fmean(currents):.3e} A, "
            f"stdev {statistics.stdev(currents):.3e} A"
        )


def _sim_devices(machine: MachineConfig, clock: Clock):
    from multilbic.sim.fake_laser import FakeLaserBoard
    from multilbic.sim.fake_marlin import FakeMarlin
    from multilbic.sim.fake_smu import FakeMiniSMU, FakeMiniSMUTransport
    from multilbic.sim.link import connect

    marlin = Marlin(connect(FakeMarlin(machine), clock), machine, clock)
    board = LaserBoard(connect(FakeLaserBoard(), clock), machine, clock)
    fake_smu = FakeMiniSMU(clock, signal=lambda ch, t: 2e-9, noise_a=1e-10)
    smu = PhotocurrentSmu(FakeMiniSMUTransport(fake_smu), clock)
    return (lambda: marlin), (lambda: board), (lambda: smu)


def _real_devices(machine: MachineConfig, clock: Clock, smu_port: str):
    ports = machine.ports()

    def need(name: str, port: str) -> str:
        if not port:
            raise RuntimeError(
                f"no {name} port for {sys.platform} in machine.toml"
            )
        return port

    return (
        lambda: Marlin(
            SerialLink.open(need("skr", ports.skr), machine.baud, clock),
            machine,
            clock,
        ),
        lambda: LaserBoard(
            SerialLink.open(need("laser", ports.laser), machine.baud, clock),
            machine,
            clock,
        ),
        lambda: open_smu(need("smu", smu_port or ports.smu), clock),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--sim", action="store_true", help="simulated devices")
    where.add_argument("--real", action="store_true", help="the machine")
    parser.add_argument("--smu-port", default="", help="miniSMU serial port")
    parser.add_argument("--rate", type=float, default=100.0, help="stream Hz")
    parser.add_argument("--home", action="store_true")
    parser.add_argument("--move", action="store_true")
    parser.add_argument("--lasers", action="store_true")
    parser.add_argument("--machine", default=None, help="machine.toml path")
    args = parser.parse_args(argv)

    machine = load(args.machine)
    # 20x: fast enough for CI, slow enough that a stalled thread on a
    # busy runner doesn't trip a simulated timeout (tests/conftest.py).
    args.clock = ScaledClock(20.0) if args.sim else SYSTEM_CLOCK
    if args.sim:
        makers = _sim_devices(machine, args.clock)
    else:
        makers = _real_devices(machine, args.clock, args.smu_port)

    failed = []
    checks = (
        ("Marlin", makers[0], lambda d: check_marlin(d, machine, args)),
        ("Laser board", makers[1], lambda d: check_laser(d, machine, args)),
        ("miniSMU", makers[2], lambda d: check_smu(d, args)),
    )
    for name, make, check in checks:
        _say(f"{name}:")
        device = None
        try:
            device = make()
            check(device)
            _say("  PASS")
        except Exception as exc:
            failed.append(name)
            _say(f"  FAIL: {type(exc).__name__}: {exc}")
            if not args.sim:
                traceback.print_exc()
        finally:
            if device is not None:
                # A device that failed may fail to close as well; the
                # failure that matters has already been reported.
                with contextlib.suppress(Exception):
                    device.close()
    _say("all devices answered" if not failed else f"failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
