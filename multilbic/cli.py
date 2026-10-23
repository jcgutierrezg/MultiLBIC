"""
The command line: calibrate a sample, then run its maps.

    uv run multilbic calibrate --sample cell-7 --out cell-7.json
    uv run multilbic calibrate --check cell-7.json
    uv run multilbic run cell-7.json --lasers 1,2,3 --pixel 0.01 \\
        --pitch 0.05 --speed 2

`calibrate` is interactive and needs you at the machine. `run` needs no
terminal once started: on the Pi, run it under `nohup ... --yes &` so a
dropped SSH connection doesn't end it. Ctrl+C, or `kill -INT <pid>` /
`kill <pid>`, is Stop: motion stops at once, lasers and SMU go off,
finished rows stay on disk.

`--sim` runs either against the simulated machine. `calibrate --sim`
puts a synthetic sample somewhere on the carriage for you to find (use
`read`); `run --sim` puts one exactly where the calibration says.
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from pathlib import Path

from multilbic.clock import SYSTEM_CLOCK, Clock, ScaledClock
from multilbic.config import load
from multilbic.config.machine import MachineConfig
from multilbic.run.calibrate import CalibrationPrompt, load_calibration
from multilbic.run.rows import ScanDevices
from multilbic.run.session import (
    RunPlanError,
    RunRequest,
    Session,
    duration,
    estimate_s,
    plan_run,
)

#: `--current-range` choices: the miniSMU's measurement ranges.
CURRENT_RANGES: dict[str, float | None] = {
    "1u": 1e-6, "25u": 25e-6, "650u": 650e-6, "15m": 15e-3, "auto": None,
}
#: Simulated runs go here (ignored by git); real ones outside the checkout.
SIM_RUNS = Path("runs")
REAL_RUNS = Path.home() / "multilbic-runs"
#: Where `calibrate --sim` hides its sample on the carriage.
SIM_CORNER_CARRIAGE_MM = (15.2, 16.1)
SIM_SAMPLE_MM = (2.0, 1.0)
SIM_SPEED = 5.0


def say(text: str) -> None:
    print(text, flush=True)


# ---- devices ----


def open_real(machine: MachineConfig, clock: Clock) -> ScanDevices:
    from multilbic.hardware.laser import LaserBoard
    from multilbic.hardware.link import SerialLink
    from multilbic.hardware.marlin import Marlin
    from multilbic.hardware.smu import open_smu

    ports = machine.ports()
    for name in ("skr", "laser", "smu"):
        if not getattr(ports, name):
            raise SystemExit(
                f"no {name} port for {sys.platform} in machine.toml"
            )
    marlin = Marlin(SerialLink.open(ports.skr, machine.baud, clock),
                    machine, clock)
    marlin.open()
    board = LaserBoard(SerialLink.open(ports.laser, machine.baud, clock),
                       machine, clock)
    board.open()
    smu = open_smu(ports.smu, clock)
    smu.identify()
    return ScanDevices(marlin, board, smu)


def sim_rig(machine: MachineConfig, clock: Clock, corner, size):
    from multilbic.sim.rig import SimRig
    from multilbic.sim.sample import SyntheticSample

    rig = SimRig(machine, clock, SyntheticSample.default(*size), corner)
    rig.open()
    return rig


def close(devices: ScanDevices) -> None:
    for device in (devices.smu, devices.laser, devices.marlin):
        try:
            device.close()
        except Exception:  # noqa: S110 - best effort on the way out
            pass


# ---- calibrate ----


def calibrate(args: argparse.Namespace) -> int:
    machine = load(args.machine)
    check = load_calibration(args.check) if args.check else None
    sample = check.sample if check else args.sample
    if not sample:
        raise SystemExit("--sample is needed (or --check a saved file)")
    out = Path(args.out or (args.check or f"{sample}.json"))
    if args.sim:
        clock: Clock = ScaledClock(SIM_SPEED)
        rig = sim_rig(machine, clock, SIM_CORNER_CARRIAGE_MM, SIM_SAMPLE_MM)
        devices = ScanDevices(rig.marlin, rig.laser, rig.smu)
        say(
            f"simulated: a {SIM_SAMPLE_MM[0]:g} x {SIM_SAMPLE_MM[1]:g} mm "
            "sample is on the carriage; find its corner with 'read'"
        )
    else:
        devices = open_real(machine, SYSTEM_CLOCK)
    prompt = CalibrationPrompt(devices, machine, sample=sample,
                               default_path=out)
    say("the stage will home and the reference laser will come on")
    try:
        prompt.start(check)
        prompt.loop()
    finally:
        prompt.stop()
        close(devices)
    return 0


# ---- run ----


def run(args: argparse.Namespace) -> int:
    machine = load(args.machine)
    calibration = load_calibration(args.calibration)
    try:
        lasers = tuple(int(n) for n in args.lasers.split(","))
    except ValueError:
        raise SystemExit(f"--lasers {args.lasers!r}: e.g. 1,2,3") from None
    request = RunRequest(
        calibration, lasers, args.pixel, args.pitch, args.speed,
        serpentine=not args.one_direction, bias_v=args.bias,
        baseline_s=args.baseline, allow_unmeasured=args.allow_unmeasured,
        note=args.note,
        current_range_a=CURRENT_RANGES[args.current_range],
    )
    try:
        plans = plan_run(request, machine)
    except (RunPlanError, ValueError) as exc:
        raise SystemExit(f"cannot run: {exc}") from None
    if not args.sim and not machine.geometry.directions_measured:
        raise SystemExit(
            "cannot run: [geometry] x_along/y_along in machine.toml have "
            "not been checked on the machine (directions_measured = false)"
        )

    settle = machine.laser_board.settle_ms / 1000
    total = estimate_s(plans, args.baseline, settle)
    say(f"sample {calibration.sample}: {calibration.width_mm:g} x "
        f"{calibration.height_mm:g} mm")
    for p in plans:
        say(f"  laser {p.laser} ({p.wavelength_nm} nm): "
            f"{len(p.raster.rows)} rows at {args.speed:g} mm/s, "
            f"{p.raster.stream_hz:g} Hz, XY {p.placement.xy_mm[0]:.3f} "
            f"{p.placement.xy_mm[1]:.3f}")
    say(f"about {duration(total)}, plus homing")
    if not args.yes:
        if not sys.stdin.isatty():
            raise SystemExit("no terminal to confirm on: pass --yes")
        if input("start? the stage will home and lasers come on [y/N] ") \
                .strip().lower() != "y":
            say("not started")
            return 1

    from multilbic.bench.report import provenance

    if args.sim:
        from multilbic.sim.rig import Faults

        clock: Clock = ScaledClock(args.speedup, precise=True)
        # The truth is where the calibration says, as a perfect
        # operator would have recorded it.
        corner = _sim_corner(calibration, machine, Faults())
        rig = sim_rig(machine, clock, corner,
                      (calibration.width_mm, calibration.height_mm))
        devices = ScanDevices(rig.marlin, rig.laser, rig.smu)
    else:
        clock = SYSTEM_CLOCK
        devices = open_real(machine, clock)
    out = Path(args.out) if args.out else (SIM_RUNS if args.sim else REAL_RUNS)
    session = Session(
        devices, machine, clock, request, out,
        simulated=args.sim, provenance=provenance(), say=say,
    )
    try:
        outcome = run_until_done(session)
    finally:
        close(devices)
    for result in outcome.lasers:
        shift = (
            f", serpentine shift {result.shift_um:.1f} µm"
            if result.shift_um is not None else ""
        )
        say(f"  laser {result.laser}: {result.status}{shift}")
    return 0 if outcome.status == "complete" else 1


def _sim_corner(calibration, machine, faults):
    """Inverse of `SimRig.perfect_calibration`: where the sample really
    is, given what a perfect operator recorded."""
    from multilbic.scan.geometry import xy_to_ab

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


def run_until_done(session: Session):
    """Run on a worker thread, so Ctrl+C and SIGTERM can stop it."""
    result = {}

    def work() -> None:
        result["outcome"] = session.run()

    worker = threading.Thread(target=work, name="run", daemon=True)

    def on_signal(signum, frame) -> None:
        if not session.stop.is_set():
            say("stopping: motion stopped, turning lasers and SMU off")
            session.request_stop()

    previous = signal.signal(signal.SIGTERM, on_signal)
    worker.start()
    try:
        while worker.is_alive():
            try:
                worker.join(0.2)
            except KeyboardInterrupt:
                on_signal(signal.SIGINT, None)
    finally:
        signal.signal(signal.SIGTERM, previous)
    return result["outcome"]


# ---- map ----


def remap(args: argparse.Namespace) -> int:
    """Rebuild a map from its run file alone and draw it again, e.g.
    after the display orientation or the mapping changed."""
    from multilbic.scan.mapping import build_map
    from multilbic.store.image import save_png
    from multilbic.store.runfile import read_run

    machine = load(args.machine)
    run = read_run(args.runfile)
    result = build_map(run.scan_data())
    out = Path(args.out) if args.out else Path(args.runfile).with_suffix(".png")
    save_png(
        result, out,
        title=f"{run.header.get('sample', '')}, laser "
        f"{run.header.get('laser', '?')} ({run.header.get('status', '?')})",
        view=machine.display.view,
    )
    shift = result.alignment
    say(f"map: {out}")
    say(
        f"serpentine shift {shift.shift_mm * 1000:.1f} µm "
        f"(quality {shift.quality:.2f})" if shift.found
        else f"serpentine shift not found (quality {shift.quality:.2f})"
    )
    return 0


# ---- entry ----


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="multilbic", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--machine", default=None, help="machine.toml path")
    commands = parser.add_subparsers(dest="command", required=True)

    cal = commands.add_parser("calibrate", help="find the sample's corner")
    cal.add_argument("--sample", default="", help="sample name")
    cal.add_argument("--out", default="", help="calibration file to write")
    cal.add_argument("--check", default="", help="re-check a saved file")
    cal.add_argument("--sim", action="store_true")
    cal.set_defaults(func=calibrate)

    go = commands.add_parser("run", help="map a calibrated sample")
    go.add_argument("calibration", help="file from 'calibrate'")
    go.add_argument("--lasers", required=True, help="e.g. 1,2,3")
    go.add_argument("--pixel", type=float, required=True, help="mm along A")
    go.add_argument("--pitch", type=float, required=True, help="mm between rows")
    go.add_argument("--speed", type=float, default=2.0, help="mm/s")
    go.add_argument("--bias", type=float, default=0.0, help="V")
    go.add_argument("--baseline", type=float, default=3.0,
                    help="s of laser-off baseline per laser")
    go.add_argument("--one-direction", action="store_true")
    go.add_argument("--current-range", default="25u",
                    choices=list(CURRENT_RANGES),
                    help="fixed SMU range; 'auto' drops samples at every "
                    "range switch (default 25u)")
    go.add_argument("--note", default="",
                    help="free text for the file headers, e.g. lighting")
    go.add_argument("--allow-unmeasured", action="store_true",
                    help="scan lasers whose positions are placeholders")
    go.add_argument("--out", default="", help="folder for runs")
    go.add_argument("--yes", action="store_true", help="don't ask to start")
    go.add_argument("--sim", action="store_true")
    go.add_argument("--speedup", type=float, default=SIM_SPEED,
                    help="simulated seconds per real second (--sim)")
    go.set_defaults(func=run)

    draw = commands.add_parser("map", help="rebuild and draw a run file's map")
    draw.add_argument("runfile", help="a laser's .csv from a run folder")
    draw.add_argument("--out", default="", help="PNG (default: next to it)")
    draw.set_defaults(func=remap)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
