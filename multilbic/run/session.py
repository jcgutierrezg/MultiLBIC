"""
A whole run: every requested laser's map of one calibrated sample.

    home -> for each laser: XY under it -> baseline -> rows -> map

Everything that can be checked is checked before anything moves
(`plan_run`): the lasers exist and are measured, XY can reach each
placement, every row fits the AB safe range, the speed and pixel work.

A run gets its own folder:

    <out>/<UTC stamp>_<sample>/
        run.json            what was asked, the plans, the outcome
        calibration.json    the calibration it used
        events.jsonl        what happened, one JSON object per line
        laser2_519nm.csv    one run file per laser (multilbic.store)
        laser2_519nm.png    its map, built from that file alone

The session runs on whatever thread calls `run()`; the command line
calls it on a worker thread so Ctrl+C can reach `request_stop()`, and
the GUI does the same. A display follows a run through two hooks,
both called on the session's thread: `on_row` with every block of
samples once it is on disk (`multilbic.run.rows.RowDone`), and `on_map`
with each laser's finished map, built from its file. Stop ends the current laser's map at once and
skips the rest. A fault does the same. Either way every finished row is
on disk, and the laser, stream and SMU output are off.
"""

from __future__ import annotations

import datetime
import json
import re
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from multilbic.clock import Clock
from multilbic.config.machine import MachineConfig
from multilbic.run.commission import CommissionError
from multilbic.run.locate import (
    LOCATE_S,
    POWER_S,
    LaserFix,
    Locator,
    PhotodiodeStops,
)
from multilbic.run.motion import approach
from multilbic.run.rows import (
    DEFAULT_BASELINE_S,
    DEFAULT_CURRENT_RANGE_A,
    DEFAULT_WARMUP_S,
    RangeClipped,
    RowDone,
    RunStopped,
    ScanDevices,
    next_range,
    run_header,
    scan_laser,
)
from multilbic.scan.geometry import Calibration, Placement, place
from multilbic.scan.raster import RasterPlan, ScanRequest, plan_raster
from multilbic.store.runfile import RunWriter
from multilbic.version import app_version

if TYPE_CHECKING:
    from multilbic.scan.mapping import MapResult


#: The miniSMU's measurement ranges, as `--current-range` and the
#: window name them: all five (docs/hardware/smu.md). "auto" autoranges, and
#: drops samples while streaming (D15).
CURRENT_RANGES: dict[str, float | None] = {
    "1u": 1e-6, "25u": 25e-6, "650u": 650e-6, "15m": 15e-3,
    "180m": 180e-3, "auto": None,
}


def range_name(current_range_a: float | None) -> str:
    """'25u' for 25e-6: the name `CURRENT_RANGES` gives a range."""
    for name, value in CURRENT_RANGES.items():
        if value == current_range_a:
            return name
    return f"{current_range_a:g} A"
#: Simulated runs go here (ignored by git); real ones outside the checkout.
SIM_RUNS = Path("runs")
REAL_RUNS = Path.home() / "multilbic-runs"


class RunPlanError(ValueError):
    pass


@dataclass(frozen=True)
class RunRequest:
    calibration: Calibration
    lasers: tuple[int, ...]
    pixel_mm: float
    pitch_mm: float
    speed_mm_s: float
    serpentine: bool = True
    bias_v: float = 0.0
    baseline_s: float = DEFAULT_BASELINE_S
    #: Allow lasers whose position in machine.toml is a placeholder.
    allow_unmeasured: bool = False
    #: Free text for the file headers: lighting, contacts, anything
    #: the data can't say for itself.
    note: str = ""
    #: Fixed measurement range in A, or None to autorange: for every
    #: laser not in `laser_ranges_a`.
    current_range_a: float | None = DEFAULT_CURRENT_RANGE_A
    #: Laser on, stage still, before each laser's first row.
    warmup_s: float = DEFAULT_WARMUP_S
    #: A range for some lasers, by number (D15 revised, D25): lasers 100x
    #: apart in brightness can't share one.
    laser_ranges_a: dict[int, float | None] = field(default_factory=dict)
    #: A laser whose range clips starts again one range up (D26).
    step_up: bool = True
    #: Locate each laser on the photodiode right after selecting it and
    #: place its map from that, not from its `xy_centre_mm`: the servo
    #: lands it within about +-0.1 mm, differently each time
    #: (`run.locate`). Needs a measured [photodiode] on an opened channel.
    locate: bool = False
    #: A laser that can't be located, after a second, broader try:
    #: "ask" (the session's `ask_not_located`; with none, the run fails),
    #: "place" (from machine.toml, as without locating) or "skip".
    if_not_located: str = "ask"

    def range_for(self, laser: int) -> float | None:
        """The measurement range laser `laser` maps with."""
        return self.laser_ranges_a.get(laser, self.current_range_a)


@dataclass(frozen=True)
class LaserPlan:
    laser: int
    wavelength_nm: int
    placement: Placement
    raster: RasterPlan


@dataclass
class LaserOutcome:
    laser: int
    path: Path
    status: str
    png: Path | None = None
    shift_um: float | None = None
    #: The range its map was made with, after any step-up.
    current_range_a: float | None = None
    #: The files of attempts that clipped and were started again.
    clipped_attempts: list[str] = field(default_factory=list)
    #: Where it was located on the photodiode, if it was.
    fix: LaserFix | None = None
    #: Why it couldn't be located, if it couldn't (then placed from
    #: machine.toml, or skipped).
    not_located: str | None = None


@dataclass
class RunOutcome:
    folder: Path
    status: str
    lasers: list[LaserOutcome] = field(default_factory=list)


def plan_run(request: RunRequest, machine: MachineConfig) -> list[LaserPlan]:
    """Check everything that can be checked without moving."""
    if not request.lasers:
        raise RunPlanError("no lasers requested")
    if len(set(request.lasers)) != len(request.lasers):
        raise RunPlanError(f"a laser is listed twice: {request.lasers}")
    if request.if_not_located not in NOT_LOCATED_CHOICES:
        raise RunPlanError(
            f"if_not_located {request.if_not_located!r}: one of "
            f"{', '.join(NOT_LOCATED_CHOICES)}")
    stray = sorted(set(request.laser_ranges_a) - set(request.lasers))
    if stray:
        raise RunPlanError(
            f"a current range is given for laser(s) {stray}, which the run "
            f"does not map (lasers {list(request.lasers)})")
    unmeasured = [
        n for n in request.lasers
        if not _laser(machine, n).measured
    ]
    if unmeasured and not request.allow_unmeasured:
        raise RunPlanError(
            f"laser(s) {unmeasured} have placeholder positions in "
            "machine.toml; their maps would land in the wrong place. "
            "Pass --allow-unmeasured to scan them anyway."
        )
    if request.locate and (machine.photodiode is None
                           or not machine.photodiode.measured):
        raise RunPlanError(
            "placing from the photodiode needs a measured [photodiode] in "
            "machine.toml (commission first)")
    xy_lo = machine.geometry.xy_take_up_mm
    plans = []
    for n in request.lasers:
        laser = _laser(machine, n)
        placement = place(
            request.calibration, laser.on_cell_xy_mm,
            machine.ab.centre_mm, n,
        )
        for axis, value, travel in zip(
            "XY", placement.xy_mm, machine.xy.travel_mm, strict=True
        ):
            if not xy_lo <= value <= travel:
                raise RunPlanError(
                    f"laser {n}: the sample needs {axis}{value:.3f}, "
                    f"outside {xy_lo:g}..{travel:g} mm"
                )
        raster = plan_raster(
            ScanRequest(
                placement.frame, request.pixel_mm, request.pitch_mm,
                request.speed_mm_s, request.serpentine,
            ),
            machine,
        )
        plans.append(LaserPlan(n, laser.wavelength_nm, placement, raster))
    return plans


def _laser(machine: MachineConfig, number: int):
    try:
        return machine.laser(number)
    except KeyError:
        raise RunPlanError(f"there is no laser {number}") from None


#: Homing all four axes (G28). Bench, 2026-10-26: 35-39 s from a run's
#: start to its first laser, of which XY's move to the sample ~8 s.
HOMING_S = 28.0
#: Per laser, beyond what is modelled: the AB approach to the first row,
#: starting the stream, the baseline's and warm-up's catch-up waits.
#: Bench, 2026-10-26: a laser's time outside its rows, baseline,
#: warm-up and settle came to 13 s.
LASER_OVERHEAD_S = 13.0
#: Building and drawing a laser's map from its file at the end: a fixed
#: part (the PNG) and a part that grows with the samples. Bench,
#: 2026-10-26: 3 s for 42,000 samples on the Pi.
MAP_FIXED_S = 2.0
MAP_PER_SAMPLE_S = 2.5e-5


@dataclass(frozen=True)
class LaserEstimate:
    laser: int
    #: XY from where it was to this laser's placement.
    travel_s: float
    #: The servo's settle and the fixed per-laser cost.
    switch_s: float
    baseline_s: float
    warmup_s: float
    rows_s: float
    map_s: float
    #: Locating it on the photodiode first, and going there and back.
    locate_s: float = 0.0
    #: Its power read on the photodiode after the map, and the trips
    #: between sample and photodiode (D31): with the locate.
    power_s: float = 0.0

    @property
    def total_s(self) -> float:
        return (self.travel_s + self.switch_s + self.baseline_s
                + self.warmup_s + self.rows_s + self.map_s + self.locate_s
                + self.power_s)


@dataclass(frozen=True)
class RunEstimate:
    homing_s: float
    lasers: tuple[LaserEstimate, ...]

    @property
    def total_s(self) -> float:
        return self.homing_s + sum(e.total_s for e in self.lasers)

    def as_dict(self) -> dict[str, Any]:
        return {
            "homing_s": round(self.homing_s, 1),
            "lasers": [
                {k: (round(v, 1) if isinstance(v, float) else v)
                 for k, v in asdict(e).items()}
                for e in self.lasers
            ],
            "total_s": round(self.total_s, 1),
        }


def estimate_run(
    plans: list[LaserPlan], request: RunRequest, machine: MachineConfig
) -> RunEstimate:
    """How long a run should take, laser by laser. What depends on the
    sample is computed from it: the rows from the raster (rows, their
    length, the speed), XY travel from the distances between placements,
    the map from the samples it will hold. Homing and a laser's fixed
    cost are measured constants (above)."""
    from multilbic.run.motion import XY_TRAVEL_FEED_MM_S
    from multilbic.scan.timing import FIRST_MOVE_DELAY_S, Trapezoid

    settle = machine.laser_board.settle_ms / 1000
    accel = machine.xy.max_accel_mm_s2
    take_up = machine.geometry.xy_take_up_mm
    where = (0.0, 0.0)  # XY after homing
    lasers = []
    for p in plans:
        x, y = p.placement.xy_mm
        distance = ((x - where[0]) ** 2 + (y - where[1]) ** 2) ** 0.5
        # The placing move ends moving up from below: one more short move.
        travel = (Trapezoid(distance, XY_TRAVEL_FEED_MM_S, accel).duration_s
                  + Trapezoid(take_up, XY_TRAVEL_FEED_MM_S, accel).duration_s
                  + 2 * FIRST_MOVE_DELAY_S) if distance > 0 else 0.0
        where = (x, y)
        samples = p.raster.stream_hz * p.raster.estimate_s
        lasers.append(LaserEstimate(
            laser=p.laser,
            travel_s=travel,
            switch_s=settle + LASER_OVERHEAD_S,
            baseline_s=request.baseline_s,
            warmup_s=request.warmup_s,
            rows_s=p.raster.estimate_s,
            map_s=MAP_FIXED_S + MAP_PER_SAMPLE_S * samples,
            locate_s=LOCATE_S if request.locate else 0.0,
            power_s=POWER_S if request.locate else 0.0,
        ))
    return RunEstimate(HOMING_S, tuple(lasers))


def duration(seconds: float) -> str:
    """'45 s', '12 min', '3 h 20 min'."""
    if seconds < 120:
        return f"{seconds:.0f} s"
    minutes = round(seconds / 60)
    if minutes < 120:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60} min"


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")[:60] or "sample"


#: What a run does with a laser it can't locate (`if_not_located`).
NOT_LOCATED_CHOICES = ("ask", "place", "skip")


class _Skipped(Exception):
    """A laser not located, and skipped: the run goes on."""


class Session:
    def __init__(
        self,
        devices: ScanDevices,
        machine: MachineConfig,
        clock: Clock,
        request: RunRequest,
        out_root: str | Path,
        *,
        simulated: bool,
        provenance: dict[str, Any],
        say: Callable[[str], None] = lambda text: None,
        home: bool = True,
        on_row: Callable[[RowDone], None] | None = None,
        on_map: Callable[[LaserOutcome, MapResult], None] | None = None,
        ask_not_located: Callable[[int, str], str] | None = None,
    ):
        """`ask_not_located(laser, why)`, for `if_not_located = "ask"`:
        "place", "skip" or "stop", called on the run's thread, which
        waits for it."""
        self.devices = devices
        self.machine = machine
        self.clock = clock
        self.request = request
        self.plans = plan_run(request, machine)
        self.simulated = simulated
        self.provenance = provenance
        self.say = say
        self.home = home
        self.on_row = on_row
        self.on_map = on_map
        self.ask_not_located = ask_not_located
        self.stop = threading.Event()
        self._locator: Locator | None = None
        if request.locate:
            pd = machine.photodiode
            assert pd is not None  # plan_run checked
            if pd.channel not in devices.smu.channels:
                raise RunPlanError(
                    f"placing from the photodiode needs SMU channel "
                    f"{pd.channel}, which wasn't opened")
            self._locator = Locator(devices, machine, clock, say=say)
            # Stop reaches the locate the way it reaches the rows.
            self._locator.halt = self.stop
        stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
        self.folder = Path(out_root) / (
            f"{stamp}_{_slug(request.calibration.sample)}"
        )
        self.run_id = self.folder.name

    def request_stop(self) -> None:
        """Stop now. Safe from any thread, including a signal handler's:
        motion stops at once (`M410`); the worker unwinds and turns the
        laser and SMU off."""
        self.stop.set()
        try:
            self.devices.marlin.quickstop()
        except Exception as exc:
            self.say(f"stop: quickstop failed: {exc}")

    # ---- the run ----

    def run(self) -> RunOutcome:
        self.folder.mkdir(parents=True, exist_ok=False)
        (self.folder / "calibration.json").write_text(
            json.dumps(self.request.calibration.to_dict(), indent=2) + "\n"
        )
        outcome = RunOutcome(self.folder, "incomplete")
        self._event("run_start", lasers=list(self.request.lasers))
        self._write_summary(outcome)
        try:
            if self.home:
                self.say("homing")
                self.devices.marlin.home()
            for plan in self.plans:
                if self.stop.is_set():
                    raise RunStopped("stopped by the operator")
                self._one_laser(plan, outcome)
            outcome.status = "complete"
        except RunStopped:
            outcome.status = "stopped"
        except Exception as exc:
            outcome.status = f"failed: {type(exc).__name__}: {exc}"
        finally:
            self._event("run_end", status=outcome.status)
            self._write_summary(outcome)
        self.say(f"run {outcome.status}: {self.folder}")
        return outcome

    def _one_laser(self, plan: LaserPlan, outcome: RunOutcome) -> None:
        n = plan.laser
        name = f"laser{n}_{plan.wavelength_nm}nm"
        path = self.folder / f"{name}.csv"
        result = LaserOutcome(n, path, "incomplete")
        outcome.lasers.append(result)
        self.say(
            f"laser {n} ({plan.wavelength_nm} nm): "
            f"{len(plan.raster.rows)} rows, about "
            f"{duration(plan.raster.estimate_s)}"
        )
        self._event("laser_start", laser=n)
        range_a = self.request.range_for(n)
        warmup_s = self.request.warmup_s
        result.current_range_a = range_a
        try:
            x, y = plan.placement.xy_mm
            fix = self._locate(n, result) if self._locator else None
            if fix is not None:
                # It selected the laser: the servo landed it here.
                result.fix = fix
                x, y = x + fix.offset_xy_mm[0], y + fix.offset_xy_mm[1]
                xy_lo = self.machine.geometry.xy_take_up_mm
                for axis, value, travel in zip(
                        "XY", (x, y), self.machine.xy.travel_mm, strict=True):
                    if not xy_lo <= value <= travel:
                        raise RunPlanError(
                            f"laser {n}: located, the sample needs "
                            f"{axis}{value:.3f}, outside {xy_lo:g}..{travel:g}")
                self._event("laser_located", **fix.as_dict())
            power = None
            if fix is not None and self._locator is not None:
                # Warmed up and its power read on the photodiode, around
                # the map (D31); the run brings the stage to the sample.
                power = PhotodiodeStops(self._locator, fix, (x, y))
            else:
                approach(self.devices.marlin, self.machine, x=x, y=y,
                         stop=self.stop)
            while True:
                header = run_header(
                    self.machine, plan.raster, n,
                    sample=self.request.calibration.sample,
                    simulated=self.simulated,
                    firmware=self._firmware(),
                    provenance=self.provenance,
                    current_range_a=range_a,
                    warmup_s=warmup_s,
                )
                header["run_id"] = self.run_id
                header["note"] = self.request.note
                header["xy_mm"] = [x, y]
                if result.fix is not None:
                    header["located"] = result.fix.as_dict()
                if result.not_located is not None:
                    header["not_located"] = result.not_located
                    header["placed_from"] = "machine.toml"
                header["calibration"] = self.request.calibration.to_dict()
                if result.clipped_attempts:
                    header["clipped_attempts"] = result.clipped_attempts
                writer = RunWriter(path, header)
                try:
                    scan_laser(
                        self.devices, self.machine, plan.raster, n, writer,
                        self.clock,
                        baseline_s=self.request.baseline_s,
                        warmup_s=warmup_s,
                        bias_v=self.request.bias_v,
                        current_range_a=range_a,
                        stop=self.stop,
                        say=self.say,
                        on_row=self.on_row,
                        power=power,
                    )
                except RangeClipped as exc:
                    bigger = next_range(range_a) if self.request.step_up \
                        else None
                    if bigger is None:
                        raise
                    range_a = self._step_up(n, path, exc, bigger, result)
                    # It was on until a moment ago: no second warm-up.
                    warmup_s = 0.0
                    if self.stop.is_set():
                        raise RunStopped("stopped by the operator") from None
                    continue
                break
            result.status = "complete"
        except _Skipped:
            result.status = f"skipped: not located ({result.not_located})"
        except RunStopped:
            result.status = "stopped"
            raise
        except Exception as exc:
            result.status = f"failed: {type(exc).__name__}: {exc}"
            raise
        finally:
            self._event("laser_end", laser=n, status=result.status)
            if path.exists():
                self._map(result)

    def _locate(self, n: int, result: LaserOutcome) -> LaserFix | None:
        """Where laser `n` landed, trying a second time with broader
        sweeps. If neither finds it: None to place it from machine.toml,
        `_Skipped` to skip it, or `RunStopped`, as `if_not_located` (or
        the operator, asked) says."""
        assert self._locator is not None
        try:
            return self._locator.locate(n)
        except CommissionError as first:
            self._stopped()
            self.say(f"laser {n}: not located ({first}); once more, with "
                     "broader sweeps")
            self._event("laser_locate_retry", laser=n, reason=str(first))
        try:
            return self._locator.locate(n, broad=True)
        except CommissionError as second:
            self._stopped()
            why = str(second)
        choice = self.request.if_not_located
        if choice == "ask":
            if self.ask_not_located is None:
                raise CommissionError(f"laser {n}: not located: {why}")
            self.say(f"laser {n}: not located ({why}); asking what to do")
            choice = self.ask_not_located(n, why)
        self._event("laser_not_located", laser=n, reason=why, choice=choice)
        if choice == "place":
            result.not_located = why
            self.say(f"laser {n}: not located; its map placed from "
                     "machine.toml, which the servo's landing can put "
                     "0.1-0.4 mm off")
            return None
        if choice == "skip":
            result.not_located = why
            self.say(f"laser {n}: not located; skipped")
            raise _Skipped(why)
        raise RunStopped("stopped by the operator")

    def _stopped(self) -> None:
        if self.stop.is_set():
            raise RunStopped("stopped by the operator")

    def _step_up(
        self, laser: int, path: Path, clip: RangeClipped, bigger: float,
        result: LaserOutcome,
    ) -> float:
        """Set the clipped attempt's file aside, named by its range, and
        say what happens next (D26). Returns the range to start again
        with."""
        kept = path.with_name(
            f"{path.stem}_{range_name(clip.range_a)}{path.suffix}")
        path.rename(kept)
        result.clipped_attempts.append(kept.name)
        result.current_range_a = bigger
        self.say(
            f"laser {laser}: clipped at {range_name(clip.range_a)} ({clip}); "
            f"starting again at {range_name(bigger)}; the clipped attempt "
            f"is kept as {kept.name}"
        )
        self._event(
            "laser_step_up", laser=laser, clipped_range_a=clip.range_a,
            peak_a=clip.peak_a, range_a=bigger, attempt_file=kept.name,
        )
        return bigger

    def _map(self, result: LaserOutcome) -> None:
        """Build the map from the file alone, as anyone later would.
        A map that can't be built (a run stopped before its first row)
        is not an error of the run."""
        from multilbic.store.alignfile import NoRows, map_file
        from multilbic.store.image import save_png

        try:
            # The alignment is saved beside the file, so the viewer opens
            # this map without searching for it again (store/alignfile).
            mapped = map_file(result.path, by="run", realign=True).result
            result.png = save_png(
                mapped, result.path.with_suffix(".png"),
                title=f"{self.request.calibration.sample}, laser "
                f"{result.laser} ({result.status})",
                view=self.machine.display.view,
            )
            if mapped.alignment.found:
                result.shift_um = mapped.alignment.shift_mm * 1000
        except NoRows:
            return
        except Exception as exc:
            self.say(f"laser {result.laser}: no map: {exc}")
            return
        if self.on_map is not None:
            try:
                self.on_map(result, mapped)
            except Exception as exc:
                self.say(f"laser {result.laser}: map display failed: "
                         f"{type(exc).__name__}: {exc}")

    def _firmware(self) -> dict[str, str | None]:
        d = self.devices
        return {
            "marlin": d.marlin.info.firmware_name if d.marlin.info else None,
            "laser": d.laser.firmware,
            "smu": d.smu.identity,
        }

    def _event(self, kind: str, **fields: Any) -> None:
        from smuniversal_lab_suite.core.event_log import EventLog

        event = {
            "time": datetime.datetime.now(datetime.UTC).isoformat(
                timespec="milliseconds"
            ),
            "run_id": self.run_id,
            "event": kind,
            "app_version": app_version(),
            **fields,
        }
        EventLog(self.folder / "events.jsonl").record(event)

    def _write_summary(self, outcome: RunOutcome) -> None:
        r = self.request
        summary = {
            "run_id": self.run_id,
            "status": outcome.status,
            "simulated": self.simulated,
            "app_version": app_version(),
            "provenance": self.provenance,
            "request": {
                "sample": r.calibration.sample,
                "lasers": list(r.lasers),
                "pixel_mm": r.pixel_mm,
                "pitch_mm": r.pitch_mm,
                "speed_mm_s": r.speed_mm_s,
                "serpentine": r.serpentine,
                "bias_v": r.bias_v,
                "baseline_s": r.baseline_s,
                "allow_unmeasured": r.allow_unmeasured,
                "note": r.note,
                "warmup_s": r.warmup_s,
                "current_range_a": r.current_range_a,
                "laser_ranges_a": {str(n): v
                                   for n, v in r.laser_ranges_a.items()},
                "step_up": r.step_up,
                "locate": r.locate,
                "if_not_located": r.if_not_located,
            },
            "plans": [
                {
                    "laser": p.laser,
                    "wavelength_nm": p.wavelength_nm,
                    "xy_mm": list(p.placement.xy_mm),
                    "current_range_a": r.range_for(p.laser),
                    "frame_origin_ab_mm": list(p.placement.frame.origin_ab_mm),
                    "rows": len(p.raster.rows),
                    "stream_hz": p.raster.stream_hz,
                    "estimate_s": round(p.raster.estimate_s, 1),
                }
                for p in self.plans
            ],
            "estimate": estimate_run(
                self.plans, self.request, self.machine).as_dict(),
            "geometry": asdict(self.machine.geometry),
            "lasers": [
                {
                    "laser": o.laser,
                    "file": o.path.name,
                    "status": o.status,
                    "png": o.png.name if o.png else None,
                    "serpentine_shift_um": o.shift_um,
                    "current_range_a": o.current_range_a,
                    "clipped_attempts": o.clipped_attempts,
                    "located": o.fix.as_dict() if o.fix else None,
                    "not_located": o.not_located,
                }
                for o in outcome.lasers
            ],
        }
        (self.folder / "run.json").write_text(
            json.dumps(summary, indent=2, default=str) + "\n"
        )
