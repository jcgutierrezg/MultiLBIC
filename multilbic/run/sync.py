"""
The sync check: step-and-measure and continuous rows over one edge, in
one session (Phase 6, steps 2 and 3).

    home -> XY under the laser -> steps -> rows at each speed -> steps

Homing is done once and XY placed once, because homing is only known to
repeat to about 0.1 mm over days (docs/hardware.md): two sessions could
differ by more than the error being measured. For the same reason every
pass covers the same patch (`window`, in the sample's frame) and the
continuous rows sit at the same B as the step rows. Step-and-measure
comes first and again last, so drift over the session shows.

Each pass is a run file of its own, written by the same code a run uses
(`scan_laser` for continuous rows, so the timing measured is the timing
maps get; `step_laser` for the steps). The laser goes off at the end of
each pass, as in a run, and later passes get a short warm-up.

    <out>/<UTC stamp>_sync_<sample>/
        sync.json           what was asked, the passes, the result
        calibration.json
        events.jsonl
        p1_steps.csv        step-and-measure
        p2_1mm_s.csv        continuous rows at 1 mm/s (and its .png)
        ...
        p5_steps.csv        step-and-measure again

The result (`analyse`) is in `multilbic.scan.sync`: the timing error
`L`, the A backlash, each pass's forward and reverse offsets, and what
the serpentine alignment said for each map, against the edges.
"""

from __future__ import annotations

import datetime
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from multilbic.clock import Clock
from multilbic.config.machine import MachineConfig
from multilbic.run.motion import RunStopped, approach
from multilbic.run.rows import (
    DEFAULT_BASELINE_S,
    DEFAULT_CURRENT_RANGE_A,
    DEFAULT_WARMUP_S,
    ScanDevices,
    run_header,
    scan_laser,
)
from multilbic.run.session import (
    HOMING_S,
    LASER_OVERHEAD_S,
    RunPlanError,
    _slug,
    duration,
)
from multilbic.run.steps import (
    DEFAULT_DWELL_S,
    DEFAULT_SETTLE_S,
    StepPlan,
    StepRequest,
    plan_steps,
    step_header,
    step_laser,
)
from multilbic.scan.geometry import Calibration, Placement, SampleFrame, place
from multilbic.scan.raster import RasterPlan, ScanRequest, plan_raster
from multilbic.store.runfile import RunWriter, read_run
from multilbic.version import app_version

DEFAULT_SPEEDS_MM_S = (1.0, 4.0, 5.0)
DEFAULT_STEP_MM = 0.01
DEFAULT_PITCH_MM = 0.1
#: Warm-up for every pass after the first: the laser was off only for
#: the moves and the baseline in between.
DEFAULT_PASS_WARMUP_S = 10.0


@dataclass(frozen=True)
class SyncRequest:
    calibration: Calibration
    laser: int
    #: The patch, in the sample's frame: (u0, u1, v0, v1) mm. None is the
    #: whole sample.
    window_mm: tuple[float, float, float, float] | None = None
    step_mm: float = DEFAULT_STEP_MM
    pitch_mm: float = DEFAULT_PITCH_MM
    speeds_mm_s: tuple[float, ...] = DEFAULT_SPEEDS_MM_S
    settle_s: float = DEFAULT_SETTLE_S
    dwell_s: float = DEFAULT_DWELL_S
    #: Step-and-measure again at the end, to see drift.
    repeat_steps: bool = True
    current_range_a: float | None = DEFAULT_CURRENT_RANGE_A
    bias_v: float = 0.0
    baseline_s: float = DEFAULT_BASELINE_S
    warmup_s: float = DEFAULT_WARMUP_S
    pass_warmup_s: float = DEFAULT_PASS_WARMUP_S
    allow_unmeasured: bool = False
    note: str = ""


@dataclass(frozen=True)
class SyncPass:
    name: str
    #: "steps" or "scan".
    kind: str
    speed_mm_s: float | None
    steps: StepPlan | None = None
    raster: RasterPlan | None = None

    @property
    def estimate_s(self) -> float:
        plan = self.steps or self.raster
        assert plan is not None
        return plan.estimate_s


@dataclass(frozen=True)
class SyncPlan:
    placement: Placement
    #: The patch in AB: every pass covers it.
    frame: SampleFrame
    passes: tuple[SyncPass, ...]

    def estimate_s(self, request: SyncRequest, settle_s: float) -> float:
        warmups = request.warmup_s + request.pass_warmup_s * (
            len(self.passes) - 1)
        per_pass = settle_s + LASER_OVERHEAD_S + request.baseline_s
        return (HOMING_S + warmups
                + sum(p.estimate_s + per_pass for p in self.passes))


def plan_sync(request: SyncRequest, machine: MachineConfig) -> SyncPlan:
    """Check everything before anything moves."""
    try:
        laser = machine.laser(request.laser)
    except KeyError:
        raise RunPlanError(f"there is no laser {request.laser}") from None
    if not laser.measured and not request.allow_unmeasured:
        raise RunPlanError(
            f"laser {request.laser} has a placeholder position in "
            "machine.toml; pass --allow-unmeasured to use it anyway")
    if any(v <= 0 for v in request.speeds_mm_s):
        raise RunPlanError("every speed must be > 0")
    cal = request.calibration
    placement = place(cal, laser.xy_centre_mm, machine.ab.centre_mm,
                      request.laser)
    for axis, value, travel in zip("XY", placement.xy_mm,
                                   machine.xy.travel_mm, strict=True):
        if not machine.geometry.xy_take_up_mm <= value <= travel:
            raise RunPlanError(f"the sample needs {axis}{value:.3f}, "
                               f"outside 0..{travel:g} mm")
    u0, u1, v0, v1 = request.window_mm or (0.0, cal.width_mm,
                                           0.0, cal.height_mm)
    if not (0 <= u0 < u1 <= cal.width_mm and 0 <= v0 < v1 <= cal.height_mm):
        raise RunPlanError(
            f"the window u {u0:g}..{u1:g}, v {v0:g}..{v1:g} mm must lie "
            f"inside the sample (0..{cal.width_mm:g} x "
            f"0..{cal.height_mm:g} mm)")
    origin = placement.frame.to_ab(u0, v0)
    frame = SampleFrame(origin, u1 - u0, v1 - v0)

    steps = plan_steps(StepRequest(frame, request.step_mm, request.pitch_mm,
                                   request.settle_s, request.dwell_s),
                       machine)
    passes = [SyncPass("p1_steps", "steps", None, steps=steps)]
    for speed in request.speeds_mm_s:
        raster = plan_raster(ScanRequest(frame, request.step_mm,
                                         request.pitch_mm, speed), machine)
        passes.append(SyncPass(f"p{len(passes) + 1}_{speed:g}mm_s", "scan",
                               speed, raster=raster))
    if request.repeat_steps:
        passes.append(SyncPass(f"p{len(passes) + 1}_steps", "steps", None,
                               steps=steps))
    return SyncPlan(placement, frame, tuple(passes))


@dataclass
class SyncOutcome:
    folder: Path
    status: str
    passes: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None


class SyncCheck:
    def __init__(
        self,
        devices: ScanDevices,
        machine: MachineConfig,
        clock: Clock,
        request: SyncRequest,
        out_root: str | Path,
        *,
        simulated: bool,
        provenance: dict[str, Any],
        say: Callable[[str], None] = lambda text: None,
        home: bool = True,
    ):
        self.devices = devices
        self.machine = machine
        self.clock = clock
        self.request = request
        self.plan = plan_sync(request, machine)
        self.simulated = simulated
        self.provenance = provenance
        self.say = say
        self.home = home
        self.stop = threading.Event()
        stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
        self.folder = Path(out_root) / (
            f"{stamp}_sync_{_slug(request.calibration.sample)}")
        self.run_id = self.folder.name

    def estimate_s(self) -> float:
        return self.plan.estimate_s(
            self.request, self.machine.laser_board.settle_ms / 1000)

    def request_stop(self) -> None:
        """As `Session.request_stop`: safe from any thread."""
        self.stop.set()
        try:
            self.devices.marlin.quickstop()
        except Exception as exc:
            self.say(f"stop: quickstop failed: {exc}")

    def run(self) -> SyncOutcome:
        self.folder.mkdir(parents=True, exist_ok=False)
        (self.folder / "calibration.json").write_text(
            json.dumps(self.request.calibration.to_dict(), indent=2) + "\n")
        outcome = SyncOutcome(self.folder, "incomplete")
        self._event("sync_start")
        self._write(outcome)
        try:
            if self.home:
                self.say("homing")
                self.devices.marlin.home()
            x, y = self.plan.placement.xy_mm
            approach(self.devices.marlin, self.machine, x=x, y=y,
                     stop=self.stop)
            for number, step in enumerate(self.plan.passes):
                if self.stop.is_set():
                    raise RunStopped("stopped by the operator")
                warmup = (self.request.warmup_s if number == 0
                          else self.request.pass_warmup_s)
                self._one_pass(step, warmup, outcome)
            outcome.status = "complete"
        except RunStopped:
            outcome.status = "stopped"
        except Exception as exc:
            outcome.status = f"failed: {type(exc).__name__}: {exc}"
        finally:
            self._event("sync_end", status=outcome.status)
            self._write(outcome)
        if outcome.status == "complete":
            try:
                outcome.result = analyse(self.folder)
            except Exception as exc:
                self.say(f"no result: {type(exc).__name__}: {exc}")
            self._write(outcome)
        self.say(f"sync check {outcome.status}: {self.folder}")
        return outcome

    def _one_pass(self, step: SyncPass, warmup_s: float,
                  outcome: SyncOutcome) -> None:
        r = self.request
        path = self.folder / f"{step.name}.csv"
        entry: dict[str, Any] = {"name": step.name, "kind": step.kind,
                                 "speed_mm_s": step.speed_mm_s,
                                 "file": path.name, "status": "incomplete"}
        outcome.passes.append(entry)
        what = ("step-and-measure" if step.kind == "steps"
                else f"rows at {step.speed_mm_s:g} mm/s")
        self.say(f"{step.name}: {what}, about {duration(step.estimate_s)}")
        self._event("pass_start", name=step.name)
        common = dict(
            sample=r.calibration.sample, simulated=self.simulated,
            firmware=self._firmware(), provenance=self.provenance,
            current_range_a=r.current_range_a, warmup_s=warmup_s,
        )
        if step.steps is not None:
            header = step_header(self.machine, step.steps, r.laser, **common)
        else:
            assert step.raster is not None
            header = run_header(self.machine, step.raster, r.laser, **common)
        header.update(run_id=self.run_id, note=r.note, sync_pass=step.name,
                      xy_mm=list(self.plan.placement.xy_mm),
                      calibration=r.calibration.to_dict())
        writer = RunWriter(path, header)
        options = dict(baseline_s=r.baseline_s, warmup_s=warmup_s,
                       bias_v=r.bias_v, current_range_a=r.current_range_a,
                       stop=self.stop, say=self.say)
        try:
            if step.steps is not None:
                step_laser(self.devices, self.machine, step.steps, r.laser,
                           writer, self.clock, **options)
            else:
                assert step.raster is not None
                scan_laser(self.devices, self.machine, step.raster, r.laser,
                           writer, self.clock, **options)
            entry["status"] = "complete"
        except RunStopped:
            entry["status"] = "stopped"
            raise
        except Exception as exc:
            entry["status"] = f"failed: {type(exc).__name__}: {exc}"
            raise
        finally:
            self._event("pass_end", name=step.name, status=entry["status"])
            if step.kind == "scan" and path.exists():
                self._png(path, step)

    def _png(self, path: Path, step: SyncPass) -> None:
        from multilbic.scan.mapping import build_map
        from multilbic.store.image import save_png

        try:
            data = read_run(path).scan_data()
            if data.anchors:
                save_png(build_map(data), path.with_suffix(".png"),
                         title=f"{self.request.calibration.sample}, laser "
                         f"{self.request.laser}, {step.speed_mm_s:g} mm/s",
                         view=self.machine.display.view)
        except Exception as exc:
            self.say(f"{step.name}: no map: {exc}")

    def _firmware(self) -> dict[str, str | None]:
        d = self.devices
        return {
            "marlin": d.marlin.info.firmware_name if d.marlin.info else None,
            "laser": d.laser.firmware,
            "smu": d.smu.identity,
        }

    def _event(self, kind: str, **fields: Any) -> None:
        from smuniversal_lab_suite.core.event_log import EventLog

        EventLog(self.folder / "events.jsonl").record({
            "time": datetime.datetime.now(datetime.UTC).isoformat(
                timespec="milliseconds"),
            "run_id": self.run_id,
            "event": kind,
            "app_version": app_version(),
            **fields,
        })

    def _write(self, outcome: SyncOutcome) -> None:
        r = self.request
        summary = {
            "run_id": self.run_id,
            "kind": "sync check",
            "status": outcome.status,
            "simulated": self.simulated,
            "app_version": app_version(),
            "provenance": self.provenance,
            "request": {
                "sample": r.calibration.sample,
                "laser": r.laser,
                "window_mm": list(r.window_mm) if r.window_mm else None,
                "step_mm": r.step_mm,
                "pitch_mm": r.pitch_mm,
                "speeds_mm_s": list(r.speeds_mm_s),
                "settle_s": r.settle_s,
                "dwell_s": r.dwell_s,
                "repeat_steps": r.repeat_steps,
                "current_range_a": r.current_range_a,
                "bias_v": r.bias_v,
                "baseline_s": r.baseline_s,
                "warmup_s": r.warmup_s,
                "pass_warmup_s": r.pass_warmup_s,
                "note": r.note,
            },
            "xy_mm": list(self.plan.placement.xy_mm),
            "frame_origin_ab_mm": list(self.plan.frame.origin_ab_mm),
            "frame_size_mm": [self.plan.frame.width_mm,
                              self.plan.frame.height_mm],
            "estimate_s": round(self.estimate_s(), 1),
            "passes": outcome.passes,
            "result": outcome.result,
        }
        (self.folder / "sync.json").write_text(
            json.dumps(summary, indent=2) + "\n")


# ---- the result ----


def analyse(
    folder: str | Path, a_range: tuple[float, float] | None = None
) -> dict[str, Any]:
    """The sync check's result from its folder's files alone, so it can
    be worked out again later. `a_range` (machine A, mm) keeps the fits
    to one edge if the patch holds several."""
    from multilbic.scan.sync import (
        Reference,
        compare_pass,
        drift,
        fit_speeds,
        is_steps,
        scan_edges,
        step_edges,
    )

    folder = Path(folder)
    files = sorted(folder.glob("p*_*.csv"),
                   key=lambda p: int(p.name[1:p.name.index("_")]))
    steps, scans = [], []
    for path in files:
        run = read_run(path)
        if run.header.get("status") != "complete":
            continue
        (steps if is_steps(run) else scans).append((path.stem, run))
    if not steps:
        raise ValueError(f"{folder}: no complete step-and-measure pass")
    step_fits = []
    step_info = []
    for name, run in steps:
        edges, failed = step_edges(run, a_range)
        step_fits.append(edges)
        widths = sorted(e.fit.width_mm for e in edges)
        step_info.append({
            "name": name,
            "rows_fitted": len(edges),
            "rows_failed": {str(k): v for k, v in failed.items()},
            "median_width_um": (widths[len(widths) // 2] * 1000
                                if widths else None),
            "edges": [{"row": e.row, "b_mm": e.b_mm, **e.fit.as_dict()}
                      for e in edges],
        })
    reference = Reference(step_fits, steps[0][1].header["pitch_mm"])
    results = [
        compare_pass(name, run.header["speed_mm_s"],
                     scan_edges(run, a_range), reference)
        for name, run in scans
    ]
    speed_fit = fit_speeds(results)
    moved = drift(step_fits[0], step_fits[-1]) if len(step_fits) > 1 else None
    return {
        "steps": step_info,
        "passes": [r.as_dict() for r in results],
        "fit": speed_fit.as_dict() if speed_fit else None,
        "drift": moved.as_dict() if moved else None,
    }


def report_lines(result: dict[str, Any]) -> list[str]:
    """The result in a few lines, for the console."""
    lines = []
    for s in result["steps"]:
        width = s["median_width_um"]
        lines.append(
            f"{s['name']}: edge in {s['rows_fitted']} rows"
            + (f", 10-90 % width {width:.1f} um" if width else "")
            + (f", {len(s['rows_failed'])} rows without" if s["rows_failed"]
               else ""))
    for p in result["passes"]:
        f, r = p["forward"], p["reverse"]
        parts = []
        if f:
            parts.append(f"forward {f['offset_um']:+.1f} um "
                         f"(spread {f['spread_um']:.1f}, {f['count']} rows)")
        if r:
            parts.append(f"reverse {r['offset_um']:+.1f} um "
                         f"(spread {r['spread_um']:.1f})")
        if p["edge_shift"]:
            parts.append(f"shift from edges {p['edge_shift']['shift_um']:.1f}"
                         " um")
        align = p["alignment_shift_um"]
        parts.append("alignment " + (f"{align:.1f} um" if align is not None
                                     else "not found"))
        lines.append(f"{p['name']}: " + ", ".join(parts))
    fit = result["fit"]
    if fit:
        lines.append(
            f"timing error L = {fit['lag_ms']:.1f} ms, A backlash "
            f"{fit['backlash_um']:.1f} um (forward at zero speed "
            f"{fit['forward_at_zero_um']:+.1f} um, lines leave "
            f"{fit['residual_um']:.1f} um RMS)")
    else:
        lines.append("one speed only: timing and backlash not separated")
    d = result["drift"]
    if d:
        lines.append(f"drift over the session: {d['drift_um']:+.1f} um "
                     f"(spread {d['spread_um']:.1f}, {d['count']} rows)")
    return lines
