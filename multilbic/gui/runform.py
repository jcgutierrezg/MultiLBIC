"""
The run setup as typed into the window, turned into a run.

No Tk here: the window hands over the fields as text, and gets back
either a `RunPlan` (the request, each laser's plan, the estimate and a
summary to show) or a `FormError` naming the field that is wrong. The
same checks as `multilbic run` makes before anything moves (`plan_run`),
run on every keystroke, so a bad value shows before Start is pressed.

`RunPlan.notes` says what the numbers mean for this sample in plain
words - rows against each laser's spot, pixels against the spot,
samples per pixel - for the window's Plan tab.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from multilbic.config.machine import MachineConfig
from multilbic.run.rows import DEFAULT_BASELINE_S, DEFAULT_WARMUP_S
from multilbic.run.session import (
    CURRENT_RANGES,
    LaserPlan,
    RunEstimate,
    RunRequest,
    estimate_run,
    plan_run,
)
from multilbic.scan.geometry import Calibration

#: Above this the B axis gets noisy (D9).
QUIET_SPEED_MM_S = 5.0


class FormError(ValueError):
    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


@dataclass
class RunForm:
    """The fields, as typed."""

    lasers: tuple[int, ...] = (2,)
    pixel_mm: str = "0.01"
    pitch_mm: str = "0.05"
    speed_mm_s: str = "2"
    current_range: str = "25u"
    bias_v: str = "0"
    baseline_s: str = f"{DEFAULT_BASELINE_S:g}"
    warmup_s: str = f"{DEFAULT_WARMUP_S:g}"
    serpentine: bool = True
    allow_unmeasured: bool = False
    note: str = ""


@dataclass(frozen=True)
class RunPlan:
    request: RunRequest
    plans: tuple[LaserPlan, ...]
    estimate: RunEstimate
    lines: tuple[str, ...]
    warnings: tuple[str, ...] = field(default=())
    notes: tuple[str, ...] = field(default=())

    @property
    def estimate_s(self) -> float:
        """The whole run, homing included."""
        return self.estimate.total_s


def eta(seconds: float) -> str:
    """'45 s', '3 min 43 s', '1 h 05 min': to the second under an hour,
    to the minute after."""
    s = max(0, round(seconds))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60:02d} s"
    minutes = round(s / 60)
    return f"{minutes // 60} h {minutes % 60:02d} min"


def spot_against_pitch(spot_um: float, pitch_um: float) -> str:
    """How a laser's rows cover the sample, in words. The spot's size is
    the 10-90 % width of its edge, so its rim still lights a little
    beyond it: "gap" means only the rim reaches there."""
    if pitch_um > spot_um:
        gap = pitch_um - spot_um
        return (f"rows {pitch_um:g} µm apart, spot {spot_um:g} µm: a "
                f"{gap:.0f} µm strip between rows gets only the spot's rim; "
                f"a pitch of {spot_um:g} µm or less covers the sample")
    overlap = 100 * (spot_um - pitch_um) / spot_um
    if overlap < 10:
        return f"rows {pitch_um:g} µm apart, spot {spot_um:g} µm: rows just touch"
    if overlap <= 50:
        return (f"rows {pitch_um:g} µm apart, spot {spot_um:g} µm: rows "
                f"overlap by {overlap:.0f} %, every point is lit")
    return (f"rows {pitch_um:g} µm apart, spot {spot_um:g} µm: rows overlap "
            f"by {overlap:.0f} %; the map can't show detail finer than the "
            f"spot, so a pitch up to about {spot_um / 2:.0f} µm would be "
            "faster for the same detail")


def plan_form(
    form: RunForm,
    calibration: Calibration | None,
    machine: MachineConfig,
    *,
    simulated: bool,
) -> RunPlan:
    """Everything that can be checked without moving. Raises
    `FormError`."""
    if calibration is None:
        raise FormError(
            "calibration",
            "no calibration yet: set the corner and the size, or load a "
            "saved calibration",
        )
    if not form.lasers:
        raise FormError("lasers", "choose at least one laser")
    pixel = _number(form.pixel_mm, "pixel", positive=True)
    pitch = _number(form.pitch_mm, "pitch", positive=True)
    speed = _number(form.speed_mm_s, "speed", positive=True)
    bias = _number(form.bias_v, "bias")
    baseline = _number(form.baseline_s, "baseline", minimum=0.0)
    warmup = _number(form.warmup_s, "warm-up", minimum=0.0)
    if form.current_range not in CURRENT_RANGES:
        raise FormError("range", f"no range {form.current_range!r}")
    if not simulated and not machine.geometry.directions_measured:
        raise FormError(
            "machine",
            "[geometry] x_along/y_along in machine.toml have not been "
            "checked on the machine (directions_measured = false)",
        )
    request = RunRequest(
        calibration, tuple(form.lasers), pixel, pitch, speed,
        serpentine=form.serpentine, bias_v=bias, baseline_s=baseline,
        allow_unmeasured=form.allow_unmeasured, note=form.note.strip(),
        current_range_a=CURRENT_RANGES[form.current_range],
        warmup_s=warmup,
    )
    try:
        plans = plan_run(request, machine)
    except ValueError as exc:
        raise FormError("plan", str(exc)) from None

    estimate = estimate_run(plans, request, machine)
    lines = [
        f"{calibration.sample}: {calibration.width_mm:g} x "
        f"{calibration.height_mm:g} mm"
    ]
    for p, e in zip(plans, estimate.lasers, strict=True):
        lines.append(
            f"laser {p.laser} ({p.wavelength_nm} nm): "
            f"{len(p.raster.rows)} rows, about {eta(e.total_s)}"
        )
    lines.append(f"about {eta(estimate.total_s)} in all, homing included")
    notes = _notes(plans, request, machine)
    warnings = []
    if speed > QUIET_SPEED_MM_S:
        warnings.append(
            f"above {QUIET_SPEED_MM_S:g} mm/s the B axis is noisy (D9)")
    if form.current_range == "auto":
        warnings.append("autoranging drops samples at every switch (D15)")
    return RunPlan(request, tuple(plans), estimate, tuple(lines),
                   tuple(warnings), tuple(notes))


def _notes(
    plans: list[LaserPlan], request: RunRequest, machine: MachineConfig
) -> list[str]:
    pitch_um = request.pitch_mm * 1000
    pixel_um = request.pixel_mm * 1000
    raster = plans[0].raster
    row_s = raster.estimate_s / max(1, len(raster.rows))
    notes = [
        f"{len(raster.rows)} rows, one every {pitch_um:g} µm, each about "
        f"{row_s:.1f} s: halving the pitch doubles the rows and the time",
        f"{pixel_um:g} µm pixels along the rows at {request.speed_mm_s:g} "
        f"mm/s: about {raster.samples_per_pixel:.0f} samples per pixel at "
        f"{raster.stream_hz:g} Hz; faster rows mean fewer",
    ]
    spots = []
    for p in plans:
        spot = machine.laser(p.laser).spot_um
        if spot is None:
            notes.append(f"laser {p.laser}: spot not measured yet "
                         "(the photodiode measures it, Phase 6)")
            continue
        spots.append(spot)
        notes.append(f"laser {p.laser}: " + spot_against_pitch(spot, pitch_um))
    if spots and pixel_um < min(spots) / 2:
        notes.append(
            f"pixels ({pixel_um:g} µm) are finer than the smallest spot "
            f"({min(spots):g} µm): neighbouring pixels share light, which "
            "is fine; the map can't show detail finer than the spot")
    return notes


def _number(
    text: str,
    name: str,
    *,
    positive: bool = False,
    minimum: float | None = None,
) -> float:
    try:
        value = float(text.strip())
    except ValueError:
        raise FormError(name, f"{name}: {text.strip()!r} is not a number") \
            from None
    if not math.isfinite(value):
        raise FormError(name, f"{name} must be a finite number")
    if positive and value <= 0:
        raise FormError(name, f"{name} must be more than 0")
    if minimum is not None and value < minimum:
        raise FormError(name, f"{name} must be at least {minimum:g}")
    return value
