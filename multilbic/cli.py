"""
The command line: calibrate a sample, then run its maps.

    uv run multilbic calibrate --sample cell-7 --out cell-7.json
    uv run multilbic calibrate --check cell-7.json
    uv run multilbic run cell-7.json --lasers 1,2,3 --pixel 0.01 \\
        --pitch 0.05 --speed 2

`gui` opens the window (Phase 5), which does both.

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

from multilbic.clock import ScaledClock
from multilbic.config import load
from multilbic.config.machine import MachineConfig
from multilbic.run.calibrate import CalibrationPrompt, load_calibration
from multilbic.run.devices import (
    SIM_SAMPLE_MM,
    SIM_SPEED,
    Connection,
    DeviceSetupError,
    open_real,
    open_sim,
    sim_corner,
)
from multilbic.run.session import (
    CURRENT_RANGES,
    REAL_RUNS,
    SIM_RUNS,
    RunPlanError,
    RunRequest,
    Session,
    duration,
    estimate_run,
    plan_run,
    range_name,
)


def say(text: str) -> None:
    print(text, flush=True)


# ---- devices ----


def connect_real(machine: MachineConfig) -> Connection:
    try:
        return open_real(machine)
    except DeviceSetupError as exc:
        raise SystemExit(f"cannot open the machine: {exc}") from None


# ---- calibrate ----


def calibrate(args: argparse.Namespace) -> int:
    machine = load(args.machine)
    check = load_calibration(args.check) if args.check else None
    sample = check.sample if check else args.sample
    if not sample:
        raise SystemExit("--sample is needed (or --check a saved file)")
    out = Path(args.out or (args.check or f"{sample}.json"))
    if args.sim:
        conn = open_sim(machine, clock=ScaledClock(SIM_SPEED))
        say(
            f"simulated: a {SIM_SAMPLE_MM[0]:g} x {SIM_SAMPLE_MM[1]:g} mm "
            "sample is on the carriage; find its corner with 'read'"
        )
    else:
        conn = connect_real(machine)
    prompt = CalibrationPrompt(conn.devices, machine, sample=sample,
                               default_path=out)
    say("the stage will home and the reference laser will come on")
    try:
        prompt.start(check)
        prompt.loop()
    finally:
        prompt.stop()
        conn.close()
    return 0


# ---- run ----


def parse_ranges(text: str) -> tuple[float | None, dict[int, float | None]]:
    """`--current-range`: '25u' for every laser, '1=650u,2=25u' per
    laser, or both ('25u,1=650u': 650u for laser 1, 25u for the rest).
    Returns (the range for lasers not named, {laser: range})."""
    default: float | None = CURRENT_RANGES["25u"]
    per_laser: dict[int, float | None] = {}
    names = ", ".join(CURRENT_RANGES)
    for item in (part.strip() for part in text.split(",")):
        if not item:
            continue
        laser_text, _, name = item.rpartition("=")
        if name not in CURRENT_RANGES:
            raise ValueError(f"no range {name!r} (ranges: {names})")
        if not laser_text:
            default = CURRENT_RANGES[name]
            continue
        try:
            laser = int(laser_text)
        except ValueError:
            raise ValueError(f"{item!r}: the laser is a number, e.g. "
                             "1=650u") from None
        if laser in per_laser:
            raise ValueError(f"laser {laser} is given twice")
        per_laser[laser] = CURRENT_RANGES[name]
    return default, per_laser


def run(args: argparse.Namespace) -> int:
    machine = load(args.machine)
    calibration = load_calibration(args.calibration)
    try:
        lasers = tuple(int(n) for n in args.lasers.split(","))
    except ValueError:
        raise SystemExit(f"--lasers {args.lasers!r}: e.g. 1,2,3") from None
    try:
        default_range, laser_ranges = parse_ranges(args.current_range)
    except ValueError as exc:
        raise SystemExit(f"--current-range: {exc}") from None
    request = RunRequest(
        calibration, lasers, args.pixel, args.pitch, args.speed,
        serpentine=not args.one_direction, bias_v=args.bias,
        baseline_s=args.baseline, allow_unmeasured=args.allow_unmeasured,
        note=args.note, warmup_s=args.warmup,
        current_range_a=default_range, laser_ranges_a=laser_ranges,
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

    estimate = estimate_run(plans, request, machine)
    say(f"sample {calibration.sample}: {calibration.width_mm:g} x "
        f"{calibration.height_mm:g} mm")
    for p, e in zip(plans, estimate.lasers, strict=True):
        say(f"  laser {p.laser} ({p.wavelength_nm} nm): "
            f"{len(p.raster.rows)} rows at {args.speed:g} mm/s, "
            f"{p.raster.stream_hz:g} Hz, range "
            f"{range_name(request.range_for(p.laser))}, XY "
            f"{p.placement.xy_mm[0]:.3f} {p.placement.xy_mm[1]:.3f}, about "
            f"{duration(e.total_s)}")
    say(f"about {duration(estimate.total_s)} in all, homing included")
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

        # The truth is where the calibration says, as a perfect
        # operator would have recorded it.
        conn = open_sim(
            machine, speed=args.speedup,
            corner_carriage_mm=sim_corner(calibration, machine, Faults()),
            size_mm=(calibration.width_mm, calibration.height_mm),
        )
    else:
        conn = connect_real(machine)
    out = Path(args.out) if args.out else (SIM_RUNS if args.sim else REAL_RUNS)
    session = Session(
        conn.devices, machine, conn.clock, request, out,
        simulated=args.sim, provenance=provenance(), say=say,
    )
    try:
        outcome = run_until_done(session)
    finally:
        conn.close()
    for result in outcome.lasers:
        shift = (
            f", serpentine shift {result.shift_um:.1f} µm"
            if result.shift_um is not None else ""
        )
        say(f"  laser {result.laser}: {result.status}{shift}")
    return 0 if outcome.status == "complete" else 1


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


# ---- gui ----


def gui(args: argparse.Namespace) -> int:
    from multilbic.gui.app import launch

    return launch(load(args.machine), simulated=args.sim,
                  speedup=args.speedup)


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
    go.add_argument("--speed", type=float, default=4.0,
                    help="mm/s (default 4, D27; 5 at most, D9)")
    go.add_argument("--bias", type=float, default=0.0, help="V")
    go.add_argument("--baseline", type=float, default=3.0,
                    help="s of laser-off baseline per laser")
    go.add_argument("--warmup", type=float, default=60.0,
                    help="s with each laser on before its first row, "
                    "for its output to settle (default 60; 0 to skip)")
    go.add_argument("--one-direction", action="store_true")
    go.add_argument("--current-range", default="25u",
                    help="fixed SMU range, one for all lasers or one per "
                    "laser: 25u, or 1=650u,2=25u,3=650u, or 25u,1=650u "
                    f"(ranges: {', '.join(CURRENT_RANGES)}; 'auto' drops "
                    "samples at every range switch; default 25u)")
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

    window = commands.add_parser("gui", help="the window")
    window.add_argument("--sim", action="store_true",
                        help="the simulated machine, with a synthetic sample "
                        "on the carriage to find")
    window.add_argument("--speedup", type=float, default=SIM_SPEED,
                        help="simulated seconds per real second (--sim)")
    window.set_defaults(func=gui)

    draw = commands.add_parser("map", help="rebuild and draw a run file's map")
    draw.add_argument("runfile", help="a laser's .csv from a run folder")
    draw.add_argument("--out", default="", help="PNG (default: next to it)")
    draw.set_defaults(func=remap)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
