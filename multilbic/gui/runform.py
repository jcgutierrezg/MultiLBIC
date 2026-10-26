"""
The run setup as typed into the window, turned into a run.

No Tk here: the window hands over the fields as text, and gets back
either a `RunPlan` (the request, each laser's plan, the estimate and a
summary to show) or a `FormError` naming the field that is wrong. The
same checks as `multilbic run` makes before anything moves (`plan_run`),
run on every keystroke, so a bad value shows before Start is pressed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from multilbic.config.machine import MachineConfig
from multilbic.run.rows import DEFAULT_BASELINE_S, DEFAULT_WARMUP_S
from multilbic.run.session import (
    CURRENT_RANGES,
    LaserPlan,
    RunRequest,
    duration,
    estimate_s,
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
    #: Rows, baselines, warm-ups and laser switching; not homing.
    estimate_s: float
    lines: tuple[str, ...]
    warnings: tuple[str, ...] = field(default=())


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

    settle = machine.laser_board.settle_ms / 1000
    total = estimate_s(plans, baseline, settle, warmup)
    lines = [
        f"{calibration.sample}: {calibration.width_mm:g} x "
        f"{calibration.height_mm:g} mm"
    ]
    for p in plans:
        lines.append(
            f"laser {p.laser} ({p.wavelength_nm} nm): "
            f"{len(p.raster.rows)} rows, {p.raster.stream_hz:g} Hz, "
            f"about {duration(p.raster.estimate_s)} of rows"
        )
    lines.append(f"about {duration(total)} in all, plus homing")
    warnings = []
    if speed > QUIET_SPEED_MM_S:
        warnings.append(
            f"above {QUIET_SPEED_MM_S:g} mm/s the B axis is noisy (D9)")
    if form.current_range == "auto":
        warnings.append("autoranging drops samples at every switch (D15)")
    return RunPlan(request, tuple(plans), total, tuple(lines),
                   tuple(warnings))


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
