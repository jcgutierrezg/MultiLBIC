"""
Focus assist with the photodiode (Phase 6 step 6, D24).

The focus is turned by hand at the laser. This measures the spot over
and over while that happens, so the operator sees at once whether a
turn made it sharper: the stage passes back and forth across one blade
edge under the laser and fits each pass's 10-90 % width.

**Getting there** is commissioning's (`Commissioner._find`, `_coarse`):
the open quarter under the laser, the light, the range, and the edge
roughly.

**Each pass** spans `FOCUS_WIDTHS` widths either side of where the last
one found the edge, so it follows a beam that moves as it is refocused,
and runs at the feed that puts about `READINGS_PER_WIDTH` readings
across the edge: about 3 s a pass whether the spot is 40 um or 400 um.
Each is fitted with its own plateau, so the laser's power drifting is
not read as a change of focus, and passes alternate direction, so the
stamp lag shifts the edge's place one way and then the other, never its
width. A pass that finds no edge (the beam went off it, or a hand was
in the way) is reported, and the next spans twice as far.

**The edges.** Passes along A cross the blade along B, which is at the
sample's height: that width is the spot the maps see. With both axes,
passes along B (the upper blade, 0.4 mm higher) alternate with them,
which shows astigmatism.

**Done** ends the passes and measures the laser again as commissioning
does (warm by now): a refocused laser has a new position. The proposal
moves that laser only; the measured corner stays (`propose`).
**Stop** stops at once, laser and channel off, nothing proposed.
"""

from __future__ import annotations

import statistics
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from multilbic.config.machine import MachineConfig
from multilbic.run.commission import (
    AXES,
    READ_S,
    Commissioner,
    CommissionError,
    CommissionRequest,
    EdgePass,
    LaserCommission,
    Proposal,
    propose,
)

#: A pass spans this many widths either side of the edge...
FOCUS_WIDTHS = 4.0
#: ...but no less, and no more, than these, mm.
FOCUS_HALF_MIN_MM = 0.15
FOCUS_HALF_MAX_MM = 1.5
#: Readings across the edge's 10-90 % width; the feed follows from it.
READINGS_PER_WIDTH = 10.0
FOCUS_FEED_MIN_MM_S = 0.02
FOCUS_FEED_MAX_MM_S = 1.0
#: Until a pass has timed it: the real SMU's single reading.
READ_INTERVAL_S = 0.038
#: The scatter shown is over this many recent good passes on an axis.
RECENT = 5
#: A missed edge widens the next pass by this.
MISS_WIDEN = 2.0


@dataclass(frozen=True)
class FocusRequest:
    laser: int
    #: 0: passes along A (the blade at the sample's height); 1: along B.
    axes: tuple[int, ...] = (0,)
    read_s: float = READ_S
    bias_v: float = 0.0
    #: Stop on its own after this many passes (tests); 0: until Done.
    max_passes: int = 0


@dataclass(frozen=True)
class FocusPass:
    number: int
    axis: int
    direction: int
    feed_mm_s: float
    #: The clock's time at the end of the pass.
    at_s: float
    width_mm: float | None
    position_mm: float | None
    step_a: float | None
    readings: int
    error: str | None
    #: On this axis, so far: the narrowest, and the mean and scatter of
    #: the last `RECENT` good passes.
    best_mm: float | None
    recent_mm: float | None
    scatter_mm: float | None

    @property
    def good(self) -> bool:
        return self.width_mm is not None

    def line(self) -> str:
        arrow = "up" if self.direction > 0 else "down"
        head = f"pass {self.number} along {AXES[self.axis]} {arrow}:"
        if self.width_mm is None:
            return f"{head} no edge ({self.error})"
        text = (f"{head} {self.width_mm * 1000:.1f} um (best "
                f"{self.best_mm * 1000:.1f} um")  # type: ignore[operator]
        if self.recent_mm is not None and self.scatter_mm is not None:
            text += (f"; last {RECENT}: {self.recent_mm * 1000:.1f} "
                     f"± {self.scatter_mm * 1000:.1f} um")
        return text + f"), edge at {self.position_mm:.4f}"

    def as_dict(self) -> dict[str, Any]:
        return {"number": self.number, "axis": AXES[self.axis],
                "direction": self.direction, "feed_mm_s": self.feed_mm_s,
                "at_s": self.at_s, "width_mm": self.width_mm,
                "position_mm": self.position_mm, "step_a": self.step_a,
                "readings": self.readings, "error": self.error}


@dataclass
class FocusResult:
    request: FocusRequest
    passes: list[FocusPass] = field(default_factory=list)
    #: The laser measured again after Done.
    final: LaserCommission | None = None
    proposal: Proposal | None = None
    error: str | None = None

    def lines(self, machine: MachineConfig) -> list[str]:
        out: list[str] = []
        if self.final is not None:
            out.extend(self.final.lines())
        if self.proposal is not None:
            out.append("proposed for machine.toml:")
            out.extend("  " + line for line in self.proposal.lines(machine))
        if self.error:
            out.append(f"no proposal: {self.error}")
        return out


@dataclass
class _Track:
    """Where one axis's edge is, and how its passes went."""
    centre_mm: float
    width_mm: float
    step_a: float
    other_mm: float
    direction: int = 1
    widths: list[float] = field(default_factory=list)


class FocusAssist(Commissioner):
    """`run()` passes until `finish()` (Done) is called, then measures
    the laser again; `request_stop()` stops at once, from any thread."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._done = threading.Event()
        self._interval_s = READ_INTERVAL_S

    def finish(self) -> None:
        """End the passes after the one under way, and measure."""
        self._done.set()

    def run_focus(self, request: FocusRequest,
                  on_pass: Callable[[FocusPass], None] = lambda p: None,
                  ) -> FocusResult:
        n = request.laser
        self.machine.laser(n)  # KeyError before anything moves
        d = self.devices
        self._bias = request.bias_v
        commission = CommissionRequest((n,), warmup_s=0.0,
                                       read_s=request.read_s,
                                       bias_v=request.bias_v)
        result = FocusResult(request)
        d.laser.off()
        try:
            self.say("homing")
            d.marlin.home()
            self._passes(request, commission, result, on_pass)
            # Measured again from the start, as commissioning does: the
            # dark needs the laser off.
            self.say(f"laser {n}: measuring it again")
            d.laser.off()
            final = LaserCommission(n)
            result.final = final
            self._laser(final, commission)
        except BaseException:
            try:
                d.marlin.quickstop()
            except Exception:  # noqa: S110 - already failing
                pass
            raise
        finally:
            for off in (d.laser.off, d.smu.output_off):
                try:
                    off()
                except Exception as exc:
                    self.say(f"switching off failed: {exc}")
        try:
            result.proposal = propose(self.machine, {n: final})
        except CommissionError as exc:
            result.error = str(exc)
        return result

    def _passes(self, request: FocusRequest, commission: CommissionRequest,
                result: FocusResult,
                on_pass: Callable[[FocusPass], None]) -> None:
        n = request.laser
        axes = tuple(dict.fromkeys(request.axes)) or (0,)
        signs = self.pd.open_signs
        quarter = self.pd.chip_mm / 4
        first = LaserCommission(n)
        light = self._find(first, commission)
        assert first.found_mm is not None
        self._coarse(first, commission, first.found_mm, light, axes)
        tracks: dict[int, _Track] = {}
        for k in axes:
            fit = first.coarse[k].fit
            assert fit is not None
            if k == 0:
                other = first.found_mm[1]
            else:
                a_fit = first.coarse[0].fit
                assert a_fit is not None
                other = a_fit.position_mm + signs[0] * quarter
            tracks[k] = _Track(fit.position_mm, fit.width_mm,
                               light * signs[k], other)
        self.say(f"laser {n}: passing across the edge"
                 + ("s" if len(axes) > 1 else "")
                 + "; turn the focus, Done when it is sharpest")
        number = 0
        while not self._done.is_set():
            for k in axes:
                if self._done.is_set():
                    break
                number += 1
                p = self._focus_pass(n, k, tracks[k], number)
                result.passes.append(p)
                on_pass(p)
                self.say(p.line())
                if request.max_passes and number >= request.max_passes:
                    self._done.set()

    def _focus_pass(self, laser: int, k: int, track: _Track,
                    number: int) -> FocusPass:
        half = min(max(FOCUS_WIDTHS * track.width_mm, FOCUS_HALF_MIN_MM),
                   FOCUS_HALF_MAX_MM)
        feed = min(max(track.width_mm
                       / (READINGS_PER_WIDTH * self._interval_s),
                       FOCUS_FEED_MIN_MM_S), FOCUS_FEED_MAX_MM_S)
        low = self._clip(laser, k, track.centre_mm - half)
        high = self._clip(laser, k, track.centre_mm + half)
        start, end = (low, high) if track.direction > 0 else (high, low)
        p: EdgePass = self._pass(laser, k, start, end, track.other_mm, feed,
                                 track.step_a)
        if len(p.positions_mm) > 1:
            self._interval_s = (abs(end - start) / feed) / len(p.positions_mm)
        direction = track.direction
        track.direction = -direction
        fit = p.fit
        if fit is None:
            track.width_mm = min(track.width_mm * MISS_WIDEN,
                                 FOCUS_HALF_MAX_MM / FOCUS_WIDTHS)
            return self._record(number, k, direction, feed, None, None, None,
                                len(p.positions_mm), p.error, track)
        track.centre_mm = fit.position_mm
        track.width_mm = fit.width_mm
        # The light drifts; the next pass is checked against this one.
        track.step_a = fit.step_a
        track.widths.append(fit.width_mm)
        return self._record(number, k, direction, feed, fit.width_mm,
                            fit.position_mm, fit.step_a,
                            len(p.positions_mm), None, track)

    def _record(self, number: int, k: int, direction: int, feed: float,
                width: float | None, position: float | None,
                step: float | None, readings: int, error: str | None,
                track: _Track) -> FocusPass:
        recent = track.widths[-RECENT:]
        return FocusPass(
            number, k, direction, feed, self.clock.now(), width, position,
            step, readings, error,
            best_mm=min(track.widths) if track.widths else None,
            recent_mm=statistics.fmean(recent) if len(recent) >= 2 else None,
            scatter_mm=statistics.stdev(recent) if len(recent) >= 2 else None,
        )
