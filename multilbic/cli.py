"""
The command line: calibrate a sample, then run its maps.

    uv run multilbic calibrate --sample cell-7 --out cell-7.json
    uv run multilbic calibrate --check cell-7.json
    uv run multilbic run cell-7.json --lasers 1,2,3 --pixel 0.01 \\
        --pitch 0.05 --speed 2

`gui` opens the window (Phase 5), which does both.

`sync-check` measures the sync error on one edge in one session
(Phase 6): step-and-measure, rows at several speeds, step-and-measure
again. `edges` fits the edge in every row of a run file, or works out a
sync check's result again from its folder. `read` reads one SMU channel
(the photodiode on 2) dark and under chosen lasers. `commission` finds
each laser and its spot with the photodiode and proposes machine.toml's
changes, writing them with `--write`.

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
from typing import TYPE_CHECKING

from multilbic.clock import ScaledClock
from multilbic.config import load
from multilbic.config.machine import MachineConfig
from multilbic.run.calibrate import (
    CalibrationPrompt,
    load_calibration,
    load_ranges,
)
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

if TYPE_CHECKING:
    from multilbic.run.sync import SyncCheck


def say(text: str) -> None:
    print(text, flush=True)


# ---- devices ----


def connect_real(machine: MachineConfig,
                 smu_channels: tuple[int, ...] = (1,)) -> Connection:
    try:
        return open_real(machine, smu_channels=smu_channels)
    except DeviceSetupError as exc:
        raise SystemExit(f"cannot open the machine: {exc}") from None


def _calibration(path: str, machine: MachineConfig):  # noqa: ANN202
    try:
        return load_calibration(path, machine)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None


# ---- calibrate ----


def calibrate(args: argparse.Namespace) -> int:
    machine = load(args.machine)
    try:
        check = (load_calibration(args.check, machine) if args.check
                 else None)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
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
                               default_path=out, clock=conn.clock)
    if check is not None:
        # Its checked ranges come back with it, so a re-save keeps them.
        prompt.cal.ranges = load_ranges(args.check)
    say("the stage will home and the reference laser will come on")
    try:
        prompt.start(check)
        prompt.loop()
    finally:
        prompt.stop()
        conn.close()
    return 0


# ---- run ----


def _range_source(laser: int, given: str | None, checked) -> str:  # noqa: ANN001
    if given is not None:
        return ""
    if laser in checked:
        return f" (checked {checked[laser].when[:10]})"
    return " (not checked for this sample)"


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
    calibration = _calibration(args.calibration, machine)
    try:
        lasers = tuple(int(n) for n in args.lasers.split(","))
    except ValueError:
        raise SystemExit(f"--lasers {args.lasers!r}: e.g. 1,2,3") from None
    checked = load_ranges(args.calibration)
    if args.current_range is None:
        # D25: each laser's range as checked on this sample at
        # calibration; 25 uA for a laser the check didn't cover.
        default_range = CURRENT_RANGES["25u"]
        laser_ranges: dict[int, float | None] = {
            n: checked[n].range_a for n in lasers if n in checked}
    else:
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
        step_up=not args.no_step_up,
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
            f"{range_name(request.range_for(p.laser))}"
            f"{_range_source(p.laser, args.current_range, checked)}, XY "
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


def run_until_done(session: Session | SyncCheck):
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


# ---- sync check (Phase 6) ----


def _floats(text: str, what: str, count: int | None = None) -> tuple[float, ...]:
    try:
        values = tuple(float(v) for v in text.split(",") if v.strip())
    except ValueError:
        raise SystemExit(
            f"{what} {text!r}: numbers separated by commas") from None
    if count is not None and len(values) != count:
        raise SystemExit(f"{what} {text!r}: {count} numbers")
    return values


def sync_check(args: argparse.Namespace) -> int:
    from multilbic.bench.report import provenance
    from multilbic.run.sync import (
        SyncCheck,
        SyncRequest,
        plan_sync,
        report_lines,
    )

    machine = load(args.machine)
    calibration = _calibration(args.calibration, machine)
    if args.current_range is None:
        checked = load_ranges(args.calibration)
        range_a = (checked[args.laser].range_a if args.laser in checked
                   else CURRENT_RANGES["25u"])
    elif args.current_range in CURRENT_RANGES:
        range_a = CURRENT_RANGES[args.current_range]
    else:
        raise SystemExit(f"--current-range {args.current_range!r}: one of "
                         f"{', '.join(CURRENT_RANGES)}")
    window = _floats(args.window, "--window", 4) if args.window else None
    request = SyncRequest(
        calibration, args.laser,
        window_mm=window,  # type: ignore[arg-type]
        step_mm=args.step, pitch_mm=args.pitch,
        speeds_mm_s=_floats(args.speeds, "--speeds"),
        settle_s=args.settle, dwell_s=args.dwell,
        repeat_steps=not args.no_repeat, current_range_a=range_a,
        bias_v=args.bias, baseline_s=args.baseline, warmup_s=args.warmup,
        pass_warmup_s=args.pass_warmup,
        allow_unmeasured=args.allow_unmeasured, note=args.note,
    )
    try:  # before opening anything: a bad request moves nothing
        plan_sync(request, machine)
    except (RunPlanError, ValueError) as exc:
        raise SystemExit(f"cannot run: {exc}") from None
    if not args.sim and not machine.geometry.directions_measured:
        raise SystemExit("cannot run: [geometry] directions not measured")

    if args.sim:
        from multilbic.sim.rig import Faults
        from multilbic.sim.sample import SyntheticSample

        u0, u1 = (window[0], window[1]) if window else (
            0.0, calibration.width_mm)
        faults = Faults(smu_stamp_lag_s=args.sim_lag_ms / 1000)
        sample = SyntheticSample.straight_edge(
            calibration.width_mm, calibration.height_mm, (u0 + u1) / 2)
        conn = open_sim(
            machine, speed=args.speedup, faults=faults, sample=sample,
            corner_carriage_mm=sim_corner(calibration, machine, faults),
        )
    else:
        conn = connect_real(machine)
    out = Path(args.out) if args.out else (SIM_RUNS if args.sim else REAL_RUNS)
    try:
        check = SyncCheck(conn.devices, machine, conn.clock, request, out,
                          simulated=args.sim, provenance=provenance(),
                          say=say)
        plan = check.plan
        say(f"sample {calibration.sample}, laser {args.laser}: patch "
            f"{plan.frame.width_mm:g} x {plan.frame.height_mm:g} mm at A "
            f"{plan.frame.origin_ab_mm[0]:.3f}, B "
            f"{plan.frame.origin_ab_mm[1]:.3f}; range {range_name(range_a)}")
        for p in plan.passes:
            if p.steps is not None:
                detail = f"{p.steps.points} points"
            else:
                assert p.raster is not None
                detail = f"{len(p.raster.rows)} rows"
            say(f"  {p.name}: {detail}, about {duration(p.estimate_s)}")
        say(f"about {duration(check.estimate_s())} in all, homing included")
        if not args.yes:
            if not sys.stdin.isatty():
                raise SystemExit("no terminal to confirm on: pass --yes")
            if input("start? the stage will home and the laser come on "
                     "[y/N] ").strip().lower() != "y":
                say("not started")
                return 1
        outcome = run_until_done(check)
    finally:
        conn.close()
    if outcome.result:
        for line in report_lines(outcome.result):
            say(line)
    return 0 if outcome.status == "complete" else 1


def edges(args: argparse.Namespace) -> int:
    """Per-row edges in a run file, or a sync check's result again."""
    from multilbic.run.sync import analyse, report_lines
    from multilbic.scan.sync import is_steps, scan_edges, step_edges
    from multilbic.store.runfile import read_run

    a_range = None
    if args.a_range:
        lo, hi = _floats(args.a_range, "--a-range", 2)
        a_range = (lo, hi)
    path = Path(args.path)
    if path.is_dir():
        for line in report_lines(analyse(path, a_range)):
            say(line)
        return 0
    run = read_run(path)
    shift_line = ""
    if is_steps(run):
        found, failed = step_edges(run, a_range)
    else:
        scanned = scan_edges(run, a_range)
        found, failed = scanned.edges, scanned.failed
        shift, align = scanned.shift, scanned.alignment_shift_mm
        shift_line = "forward/reverse shift from edges " + (
            f"{shift.shift_mm * 1000:.1f} um (spread "
            f"{shift.spread_mm * 1000:.1f}, {shift.count} rows)"
            if shift else "not found") + ", alignment " + (
            f"{align * 1000:.1f} um" if align is not None else "not found")
    say("row  dir   B mm      edge A mm   +-um   10-90 um")
    for e in found:
        f = e.fit
        say(f"{e.row:3d}  {e.direction:+d}  {e.b_mm:9.4f}  "
            f"{f.position_mm:10.4f}  {f.position_err_mm * 1000:5.1f}  "
            f"{f.width_mm * 1000:8.1f}")
    for row, why in sorted(failed.items()):
        say(f"{row:3d}  no edge: {why}")
    if found:
        widths = sorted(e.fit.width_mm for e in found)
        say(f"median 10-90 % width {widths[len(widths) // 2] * 1000:.1f} um "
            f"over {len(found)} rows")
    if shift_line:
        say(shift_line)
    return 0


# ---- read ----


def read(args: argparse.Namespace) -> int:
    import json

    from multilbic.run.reading import read_channel

    machine = load(args.machine)
    lasers = ([int(n) for n in _floats(args.lasers, "--lasers")]
              if args.lasers else [])
    for n in lasers:
        try:
            machine.laser(n)
        except KeyError:
            raise SystemExit(f"no laser {n} in machine.toml") from None
    try:
        # Autorange unless the text names a range for every laser.
        default_range, ranges = parse_ranges("auto," + args.current_range)
        places = parse_places(args.at)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    for n in (*ranges, *places):
        if n not in lasers:
            raise SystemExit(f"laser {n} has a range or place but is not in "
                             "--lasers")
    channels = (args.channel,)
    if args.sim:
        conn = open_sim(machine, speed=args.speedup, smu_channels=channels)
    else:
        if lasers and not args.yes:
            if not sys.stdin.isatty():
                raise SystemExit("no terminal to confirm on: pass --yes")
            motion = ("the stage will home and move to each laser's place"
                      if places else "the stage will not move")
            if input(f"laser{'s' if len(lasers) > 1 else ''} "
                     f"{', '.join(map(str, lasers))} will come on, one at a "
                     f"time; {motion} [y/N] ").strip().lower() != "y":
                say("not started")
                return 1
        conn = connect_real(machine, channels)
    try:
        result = read_channel(
            conn.devices, machine, conn.clock, channel=args.channel,
            lasers=lasers, read_s=args.seconds, settle_s=args.settle,
            bias_v=args.bias, current_range_a=default_range, ranges=ranges,
            places=places, say=say)
    except KeyboardInterrupt:
        say("stopped: every laser and the channel off, motion stopped")
        return 1
    finally:
        conn.close()
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(
            {"schema": "multilbic-read/1", "simulated": args.sim,
             **result.as_dict()}, indent=2) + "\n")
        say(f"saved {out}")
    return 0


# ---- commission ----


class _CommissionJob:
    """A commissioning as `run_until_done` runs it: its outcome is the
    result, or the exception that ended it."""

    def __init__(self, commissioner, request) -> None:  # noqa: ANN001
        self.commissioner = commissioner
        self.request = request
        self.stop = commissioner.halt

    def request_stop(self) -> None:
        self.commissioner.request_stop()

    def run(self):  # noqa: ANN201
        try:
            return self.commissioner.run(self.request), None
        except BaseException as exc:  # noqa: BLE001 - reported by the caller
            return None, exc


def machine_file(given: str | None) -> Path:
    """The machine.toml in use: the one given, or the packaged one (the
    repository's own file in an editable install, as on the Pi)."""
    if given:
        return Path(given)
    from importlib import resources

    return Path(str(resources.files("multilbic.config").joinpath(
        "machine.toml")))


def commission(args: argparse.Namespace) -> int:
    import datetime

    from multilbic.bench.report import provenance
    from multilbic.run.commission import (
        Commissioner,
        CommissionError,
        CommissionRequest,
        apply_proposal,
        estimate_s,
        folder_name,
        write_report,
    )
    from multilbic.run.motion import RunStopped

    machine = load(args.machine)
    pd = machine.photodiode
    if pd is None:
        raise SystemExit("machine.toml has no [photodiode]")
    lasers = tuple(int(n) for n in _floats(args.lasers, "--lasers"))
    for n in lasers:
        try:
            machine.laser(n)
        except KeyError:
            raise SystemExit(f"no laser {n} in machine.toml") from None
    if not args.sim and not machine.geometry.directions_measured:
        raise SystemExit("cannot run: [geometry] directions not measured")
    request = CommissionRequest(
        lasers, warmup_s=args.warmup, read_s=args.read, bias_v=args.bias,
        coarse_feed_mm_s=args.coarse_feed, fine_feed_mm_s=args.fine_feed,
        note=args.note)
    say(f"lasers {', '.join(map(str, lasers))}: about "
        f"{duration(estimate_s(request, lasers))}, homing included")
    if args.sim:
        from multilbic.run.rows import ScanDevices
        from multilbic.sim.rig import Faults, SimRig
        from multilbic.sim.sample import SyntheticSample

        rig_args: dict = {}
        offsets = parse_places_like(args.sim_offset, 2, "--sim-offset")
        if offsets:
            rig_args["laser_xy_mm"] = {
                n: (machine.laser(n).xy_centre_mm[0] + dx,
                    machine.laser(n).xy_centre_mm[1] + dy)
                for n, (dx, dy) in offsets.items()}
        clock = ScaledClock(args.speedup, precise=True)
        rig = SimRig(machine, clock, SyntheticSample.default(),
                     (15.0, 16.0), Faults(), smu_channels=(pd.channel,),
                     **rig_args)
        if args.sim_corner:
            da, db = _floats(args.sim_corner, "--sim-corner", 2)
            assert rig.photodiode is not None
            c = rig.photodiode.corner_mm
            rig.photodiode.corner_mm = (c[0] + da, c[1] + db)
        rig.open()
        conn = Connection(ScanDevices(rig.marlin, rig.laser, rig.smu),
                          clock, True, rig=rig)
    else:
        if not args.yes:
            if not sys.stdin.isatty():
                raise SystemExit("no terminal to confirm on: pass --yes")
            if input("start? the stage will home, then go to the "
                     "photodiode under each laser, which comes on [y/N] "
                     ).strip().lower() != "y":
                say("not started")
                return 1
        conn = connect_real(machine, (pd.channel,))
    try:
        commissioner = Commissioner(conn.devices, machine, conn.clock,
                                    say=say)
        result, failure = run_until_done(
            _CommissionJob(commissioner, request))  # type: ignore[arg-type]
    finally:
        conn.close()
    if failure is not None:
        if isinstance(failure, RunStopped):
            say("stopped")
            return 1
        if isinstance(failure, CommissionError):
            raise SystemExit(f"commissioning failed: {failure}")
        raise failure
    out = Path(args.out) if args.out else (SIM_RUNS if args.sim else REAL_RUNS)
    folder = out / folder_name(args.sim)
    report = write_report(folder, machine, result, simulated=args.sim,
                          provenance=provenance())
    for line in result.lines(machine):
        say(line)
    say(f"report: {report}")
    if result.proposal is None:
        return 1
    path = machine_file(args.machine)
    when = datetime.date.today().isoformat()
    try:
        text = apply_proposal(path.read_text(encoding="utf-8"),
                              result.proposal, when)
    except CommissionError as exc:
        raise SystemExit(str(exc)) from None
    proposed = folder / "machine-proposed.toml"
    proposed.write_text(text, encoding="utf-8", newline="")
    say(f"proposed machine.toml: {proposed}")
    if not args.write:
        say("not written (--write writes it)")
        return 0
    if not args.yes:
        if not sys.stdin.isatty():
            raise SystemExit("no terminal to confirm on: pass --yes")
        if input(f"write these changes to {path}? [y/N] "
                 ).strip().lower() != "y":
            say("not written")
            return 0
    path.write_text(text, encoding="utf-8", newline="")
    say(f"written: {path}" + ("" if args.machine else
                              " (commit it: a deploy resets the checkout)"))
    return 0


def parse_places_like(
    items: list[str] | None, count: int, flag: str,
) -> dict[int, tuple[float, ...]]:
    """`N=v1,v2,...` once per laser, `count` values each."""
    out: dict[int, tuple[float, ...]] = {}
    for item in items or []:
        laser_text, sep, rest = item.partition("=")
        try:
            laser = int(laser_text)
            values = tuple(float(v) for v in rest.split(","))
        except ValueError:
            values = ()
        if not sep or len(values) != count:
            raise SystemExit(f"{flag} {item!r}: laser=" +
                             ",".join(["v"] * count))
        out[laser] = values
    return out


def parse_places(
    items: list[str] | None,
) -> dict[int, tuple[float, float, float, float]]:
    """`--at 1=100,70,33.2,19.3`, once per laser: {laser: (X, Y, A, B)}."""
    places: dict[int, tuple[float, float, float, float]] = {}
    for item in items or []:
        laser_text, sep, rest = item.partition("=")
        try:
            laser = int(laser_text)
            values = [float(v) for v in rest.split(",")]
        except ValueError:
            values = []
        if not sep or len(values) != 4:
            raise ValueError(f"--at {item!r}: laser=X,Y,A,B, e.g. "
                             "1=100,70,33.2,19.3")
        if laser in places:
            raise ValueError(f"laser {laser} is given two places")
        places[laser] = (values[0], values[1], values[2], values[3])
    return places


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
    go.add_argument("--current-range", default=None,
                    help="fixed SMU range, one for all lasers or one per "
                    "laser: 25u, or 1=650u,2=25u,3=650u, or 25u,1=650u "
                    f"(ranges: {', '.join(CURRENT_RANGES)}; 'auto' drops "
                    "samples at every range switch). Default: the ranges "
                    "checked at calibration ('ranges' in calibrate), 25u "
                    "for a laser not checked")
    go.add_argument("--no-step-up", action="store_true",
                    help="a laser whose range clips fails the run, instead "
                    "of starting again one range up (D26)")
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

    reading = commands.add_parser(
        "read", help="read one SMU channel dark and under lasers, no motion")
    reading.add_argument("--channel", type=int, choices=(1, 2), default=2,
                         help="SMU channel (default 2, the photodiode)")
    reading.add_argument("--lasers", default="",
                         help="lasers to read under, one at a time, e.g. "
                         "1,2,3 (default: dark only)")
    reading.add_argument("--seconds", type=float, default=2.0,
                         help="s each reading averages")
    reading.add_argument("--settle", type=float, default=2.0,
                         help="s with a laser on before reading it")
    reading.add_argument("--bias", type=float, default=0.0, help="V")
    reading.add_argument("--current-range", default="",
                         help="fixed SMU range, its full scale also the "
                         "current limit: one for all (15m) or per laser "
                         "(1=650u,2=25u,3=15m), each with its own dark "
                         f"({', '.join(CURRENT_RANGES)}; default auto, "
                         "limited to 1 mA)")
    reading.add_argument("--at", action="append", metavar="N=X,Y,A,B",
                         help="where to read laser N, once per laser: the "
                         "stage homes first and goes there (default: no "
                         "motion)")
    reading.add_argument("--out", default="", help="JSON file to save to")
    reading.add_argument("--yes", action="store_true",
                         help="don't ask before lighting lasers")
    reading.add_argument("--sim", action="store_true")
    reading.add_argument("--speedup", type=float, default=SIM_SPEED,
                         help="simulated seconds per real second (--sim)")
    reading.set_defaults(func=read)

    com = commands.add_parser(
        "commission", help="find each laser and its spot with the "
        "photodiode, and propose machine.toml's changes")
    com.add_argument("--lasers", default="1,2,3",
                     help="e.g. 1,2,3 (default); include the reference "
                     "laser (2) until the photodiode's corner is measured")
    com.add_argument("--warmup", type=float, default=60.0,
                     help="s with each laser on before reading it")
    com.add_argument("--read", type=float, default=2.0,
                     help="s each power or dark reading averages")
    com.add_argument("--bias", type=float, default=0.0, help="V")
    com.add_argument("--coarse-feed", type=float, default=0.5,
                     help="mm/s of the passes that find each edge")
    com.add_argument("--fine-feed", type=float, default=0.05,
                     help="mm/s of the passes that measure it")
    com.add_argument("--note", default="")
    com.add_argument("--out", default="", help="folder for runs")
    com.add_argument("--write", action="store_true",
                     help="write the proposed changes into machine.toml "
                     "(asks first unless --yes)")
    com.add_argument("--yes", action="store_true",
                     help="don't ask to start, or to write")
    com.add_argument("--sim", action="store_true")
    com.add_argument("--sim-offset", action="append", metavar="N=DX,DY",
                     help="(--sim) laser N really sits this far in mm from "
                     "its xy_centre_mm")
    com.add_argument("--sim-corner", default="", metavar="DA,DB",
                     help="(--sim) the corner really sits this far from "
                     "machine.toml's")
    com.add_argument("--speedup", type=float, default=SIM_SPEED,
                     help="simulated seconds per real second (--sim)")
    com.set_defaults(func=commission)

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

    sync = commands.add_parser(
        "sync-check",
        help="step-and-measure against rows at several speeds, on one edge")
    sync.add_argument("calibration", help="file from 'calibrate'")
    sync.add_argument("--laser", type=int, required=True)
    sync.add_argument("--window", default="",
                      help="the patch in the sample's frame, u0,u1,v0,v1 mm "
                      "(default: the whole sample); keep it small, steps "
                      "take about half a second a point")
    sync.add_argument("--step", type=float, default=0.01,
                      help="mm between points, and the rows' pixel")
    sync.add_argument("--pitch", type=float, default=0.1,
                      help="mm between rows")
    sync.add_argument("--speeds", default="1,4,5", help="mm/s, e.g. 1,4,5")
    sync.add_argument("--settle", type=float, default=0.2,
                      help="s to wait at each point before measuring")
    sync.add_argument("--dwell", type=float, default=0.2,
                      help="s to measure at each point (rounded up to "
                      "whole mains periods)")
    sync.add_argument("--no-repeat", action="store_true",
                      help="skip step-and-measure at the end (drift)")
    sync.add_argument("--current-range", default=None,
                      help="fixed SMU range (default: the calibration's "
                      "checked range for the laser, else 25u)")
    sync.add_argument("--bias", type=float, default=0.0, help="V")
    sync.add_argument("--baseline", type=float, default=3.0)
    sync.add_argument("--warmup", type=float, default=60.0,
                      help="s with the laser on before the first pass")
    sync.add_argument("--pass-warmup", type=float, default=10.0,
                      help="s before each later pass")
    sync.add_argument("--note", default="")
    sync.add_argument("--allow-unmeasured", action="store_true")
    sync.add_argument("--out", default="", help="folder for runs")
    sync.add_argument("--yes", action="store_true", help="don't ask to start")
    sync.add_argument("--sim", action="store_true",
                      help="the simulated machine, with a straight edge in "
                      "the middle of the patch")
    sync.add_argument("--sim-lag-ms", type=float, default=18.6,
                      help="stamp lag the simulated SMU has (--sim)")
    sync.add_argument("--speedup", type=float, default=SIM_SPEED,
                      help="simulated seconds per real second (--sim)")
    sync.set_defaults(func=sync_check)

    fit = commands.add_parser(
        "edges", help="fit the edge in each row of a run file, or a sync "
        "check's folder")
    fit.add_argument("path", help="a run file (.csv) or a sync check folder")
    fit.add_argument("--a-range", default="",
                     help="machine A lo,hi mm: fit only the edge in there")
    fit.set_defaults(func=edges)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
