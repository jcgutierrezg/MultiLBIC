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
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Any

from multilbic.clock import Clock
from multilbic.config.machine import MachineConfig
from multilbic.run.motion import approach
from multilbic.run.rows import (
    DEFAULT_BASELINE_S,
    DEFAULT_CURRENT_RANGE_A,
    DEFAULT_WARMUP_S,
    RowDone,
    RunStopped,
    ScanDevices,
    run_header,
    scan_laser,
)
from multilbic.scan.geometry import Calibration, Placement, place
from multilbic.scan.raster import RasterPlan, ScanRequest, plan_raster
from multilbic.store.runfile import RunWriter, read_run

if TYPE_CHECKING:
    from multilbic.scan.mapping import MapResult


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
    #: Fixed measurement range in A, or None to autorange.
    current_range_a: float | None = DEFAULT_CURRENT_RANGE_A
    #: Laser on, stage still, before each laser's first row.
    warmup_s: float = DEFAULT_WARMUP_S


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
    xy_lo = machine.geometry.xy_take_up_mm
    plans = []
    for n in request.lasers:
        laser = _laser(machine, n)
        placement = place(
            request.calibration, laser.xy_centre_mm,
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


def estimate_s(
    plans: list[LaserPlan],
    baseline_s: float,
    settle_s: float,
    warmup_s: float = 0.0,
) -> float:
    """Rows, baselines, warm-ups and laser switching; homing not
    included."""
    return sum(
        p.raster.estimate_s + baseline_s + settle_s + warmup_s for p in plans
    )


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
    ):
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
        self.stop = threading.Event()
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
        try:
            x, y = plan.placement.xy_mm
            approach(self.devices.marlin, self.machine, x=x, y=y,
                     stop=self.stop)
            header = run_header(
                self.machine, plan.raster, n,
                sample=self.request.calibration.sample,
                simulated=self.simulated,
                firmware=self._firmware(),
                provenance=self.provenance,
                current_range_a=self.request.current_range_a,
                warmup_s=self.request.warmup_s,
            )
            header["run_id"] = self.run_id
            header["note"] = self.request.note
            header["xy_mm"] = list(plan.placement.xy_mm)
            header["calibration"] = self.request.calibration.to_dict()
            writer = RunWriter(path, header)
            scan_laser(
                self.devices, self.machine, plan.raster, n, writer,
                self.clock,
                baseline_s=self.request.baseline_s,
                warmup_s=self.request.warmup_s,
                bias_v=self.request.bias_v,
                current_range_a=self.request.current_range_a,
                stop=self.stop,
                say=self.say,
                on_row=self.on_row,
            )
            result.status = "complete"
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

    def _map(self, result: LaserOutcome) -> None:
        """Build the map from the file alone, as anyone later would.
        A map that can't be built (a run stopped before its first row)
        is not an error of the run."""
        from multilbic.scan.mapping import build_map
        from multilbic.store.image import save_png

        try:
            data = read_run(result.path).scan_data()
            if not data.anchors:
                return
            mapped = build_map(data)
            result.png = save_png(
                mapped, result.path.with_suffix(".png"),
                title=f"{self.request.calibration.sample}, laser "
                f"{result.laser} ({result.status})",
                view=self.machine.display.view,
            )
            if mapped.alignment.found:
                result.shift_um = mapped.alignment.shift_mm * 1000
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
            "app_version": version("multilbic"),
            **fields,
        }
        EventLog(self.folder / "events.jsonl").record(event)

    def _write_summary(self, outcome: RunOutcome) -> None:
        r = self.request
        summary = {
            "run_id": self.run_id,
            "status": outcome.status,
            "simulated": self.simulated,
            "app_version": version("multilbic"),
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
            },
            "plans": [
                {
                    "laser": p.laser,
                    "wavelength_nm": p.wavelength_nm,
                    "xy_mm": list(p.placement.xy_mm),
                    "frame_origin_ab_mm": list(p.placement.frame.origin_ab_mm),
                    "rows": len(p.raster.rows),
                    "stream_hz": p.raster.stream_hz,
                    "estimate_s": round(p.raster.estimate_s, 1),
                }
                for p in self.plans
            ],
            "geometry": asdict(self.machine.geometry),
            "lasers": [
                {
                    "laser": o.laser,
                    "file": o.path.name,
                    "status": o.status,
                    "png": o.png.name if o.png else None,
                    "serpentine_shift_um": o.shift_um,
                }
                for o in outcome.lasers
            ],
        }
        (self.folder / "run.json").write_text(
            json.dumps(summary, indent=2, default=str) + "\n"
        )
