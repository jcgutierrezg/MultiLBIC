"""
Lining the lasers up on a cell: where each laser really lands on a
sample, against where the photodiode puts it.

Each laser is placed from the photodiode (`run.locate`), but its beam
meets the blades a little above the cell, each at its own angle, so on
the cell it can land tens of um from where the blades said. On the bench
(2026-11-05) the six lasers put the same cell edge up to 45 um apart
along A and 100 um along B, each the same way run after run.

The line-up measures that: a short run of the chosen lasers over a
patch centred on a cell's corner, placed from the photodiode, then in
each laser's map the cell's two edges, the one crossing the rows (its
position along u, A) and the one crossing the columns (along v, B).
Against the reference laser's (`[geometry] reference_laser`), each
laser's difference is how far its map sits off; turned into XY, it is
added to the laser's `cell_offset_xy_mm`, which runs add to where they
place it. The reference laser's offset stays 0: the corner calibration
is made under it, so its view is the sample's.

    multilbic lineup RUN_FOLDER [--write]

or the Maintenance window's Line-up tab, which makes the run too.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from multilbic.config.machine import MachineConfig, parse
from multilbic.scan.edges import NoEdge, fit_edge
from multilbic.scan.geometry import Calibration, ab_to_xy
from multilbic.scan.mapping import MapResult, build_map
from multilbic.store.runfile import read_run

#: The patch: this square, centred on the calibration's corner, which is
#: to be the cell's corner. Each edge then crosses half the rows or
#: columns, with half the patch on either side of it.
PATCH_MM = 1.2
#: Rows this far apart: the edge crossing the columns is measured along
#: them, and a finer pitch puts more points across it.
PITCH_MM = 0.025
PIXEL_MM = 0.01
SPEED_MM_S = 4.0
#: Each row's (or column's) edge is fitted this far either side of
#: where the rows agree it is: fingers further off stay out.
EDGE_WINDOW_MM = 0.25
#: Rows whose biggest step is at least this share of the clearest
#: crossings' (the 90th percentile) cross the edge; the rest are off
#: the cell.
CROSSING_SHARE = 0.5
#: Fewer rows (or columns) than this through an edge, and its position
#: is not trusted.
MIN_CROSSINGS = 5
#: An edge whose rows disagree by more than this (interquartile range)
#: is not trusted either.
MAX_SPREAD_MM = 0.04


class LineUpError(RuntimeError):
    pass


@dataclass(frozen=True)
class Edge:
    #: The median of the rows' (or columns') fitted 50 % points, mm.
    position_mm: float
    #: Their interquartile range, mm.
    spread_mm: float
    count: int
    #: The spot's 10-90 % width across this edge, mm (the median).
    width_mm: float

    @property
    def trusted(self) -> bool:
        return self.count >= MIN_CROSSINGS and self.spread_mm <= MAX_SPREAD_MM


@dataclass(frozen=True)
class CellEdges:
    """One laser's map: the cell's edge crossing its rows (along u) and
    the one crossing its columns (along v)."""

    laser: int
    u: Edge | None
    v: Edge | None
    #: The serpentine shift its map was aligned with, um; None if none
    #: was found.
    shift_um: float | None


def centred_patch(calibration: Calibration,
                  size_mm: float = PATCH_MM) -> Calibration:
    """The calibration, its corner moved half a patch back along A and B
    and its size the patch's: the cell's corner, where the calibration
    was set, is then in the middle."""
    a, b = calibration.corner_ab_mm
    half = size_mm / 2
    return replace(calibration, corner_ab_mm=(a - half, b - half),
                   width_mm=size_mm, height_mm=size_mm,
                   sample=f"{calibration.sample}-lineup")


def _edge(coords: np.ndarray, profiles: list[np.ndarray]) -> Edge | None:
    """The one edge the profiles cross: found where the profiles that
    cross it agree their biggest step is (an edge fitted to each whole
    profile, which a dim laser's noise doesn't fool as a steepest slope
    does), then fitted again in each, close round it."""
    steepest: list[tuple[float, float, np.ndarray]] = []
    for profile in profiles:
        if np.isfinite(profile).sum() < 10:
            continue
        try:
            fit = fit_edge(coords, profile)
        except NoEdge:
            continue
        steepest.append((abs(fit.step_a), fit.position_mm, profile))
    if not steepest:
        return None
    # Against the rows that cross it most clearly, not the single
    # biggest step: one row with a spike would set the bar too high.
    strongest = float(np.percentile([s for s, _, _ in steepest], 90))
    crossing = [(x, p) for s, x, p in steepest
                if s >= CROSSING_SHARE * strongest]
    where = float(np.median([x for x, _ in crossing]))
    fits = []
    for _, profile in crossing:
        try:
            fits.append(fit_edge(
                coords, profile,
                x_range=(where - EDGE_WINDOW_MM, where + EDGE_WINDOW_MM)))
        except NoEdge:
            continue
    fits = [f for f in fits if abs(f.position_mm - where) <= EDGE_WINDOW_MM]
    if not fits:
        return None
    pos = np.array([f.position_mm for f in fits])
    q1, q3 = np.percentile(pos, [25, 75])
    return Edge(float(np.median(pos)), float(q3 - q1), len(fits),
                float(np.median([f.width_mm for f in fits])))


def cell_edges(laser: int, result: MapResult) -> CellEdges:
    g = result.grid
    rows = [g.values[i] for i in range(g.values.shape[0])]
    columns = [g.values[:, j] for j in range(g.values.shape[1])]
    a = result.alignment
    return CellEdges(
        laser,
        _edge(g.u_centres, rows),
        _edge(g.v_centres, columns),
        a.shift_mm * 1000 if a.found else None,
    )


@dataclass
class LineUp:
    """The lasers' edges against the reference laser's, and the offsets
    that would put every map on the reference's."""

    reference: int
    edges: dict[int, CellEdges]
    #: Each laser's `cell_offset_xy_mm` when the run was made.
    used_xy_mm: dict[int, tuple[float, float]]
    #: The offsets to write, by laser (the reference's included, 0).
    proposal: dict[int, tuple[float, float]] = field(default_factory=dict)
    #: Lasers left out of the proposal, and why.
    left_out: dict[int, str] = field(default_factory=dict)
    error: str | None = None

    def spread_um(self) -> tuple[float | None, float | None]:
        """How far apart the trusted lasers put each edge, um."""
        out: list[float | None] = []
        for axis in ("u", "v"):
            values = [getattr(e, axis).position_mm for e in self.edges.values()
                      if getattr(e, axis) is not None
                      and getattr(e, axis).trusted]
            out.append((max(values) - min(values)) * 1000
                       if len(values) > 1 else None)
        return out[0], out[1]

    def lines(self, machine: MachineConfig) -> list[str]:
        out = [f"reference: laser {self.reference}"]
        for n in sorted(self.edges):
            e = self.edges[n]
            parts = [f"laser {n}:"]
            for axis, edge in (("u", e.u), ("v", e.v)):
                if edge is None:
                    parts.append(f"{axis} none")
                else:
                    mark = "" if edge.trusted else " (not trusted)"
                    parts.append(
                        f"{axis} {edge.position_mm:.3f} mm "
                        f"(spread {edge.spread_mm * 1000:.0f} um, "
                        f"n {edge.count}){mark}")
            if e.shift_um is not None:
                parts.append(f"shift {e.shift_um:+.0f} um")
            out.append("  ".join(parts))
        su, sv = self.spread_um()
        out.append("spread: " + ", ".join(
            f"{axis} {s:.0f} um" if s is not None else f"{axis} -"
            for axis, s in (("u", su), ("v", sv))))
        for n in sorted(self.proposal):
            old = machine.laser(n).cell_offset_xy_mm
            new = self.proposal[n]
            out.append(f"laser {n}: cell_offset_xy_mm "
                       f"[{old[0]:.3f}, {old[1]:.3f}] -> "
                       f"[{new[0]:.3f}, {new[1]:.3f}]")
        for n, why in sorted(self.left_out.items()):
            out.append(f"laser {n}: left as it is ({why})")
        if self.error:
            out.append(f"no proposal: {self.error}")
        return out


def line_up(
    edges: dict[int, CellEdges],
    used_xy_mm: dict[int, tuple[float, float]],
    machine: MachineConfig,
) -> LineUp:
    """The offsets that put each laser's edges on the reference's.

    A laser's map shows the cell where the beam really was: a beam
    landing `d` further along A than its placement assumed shows every
    feature `d` further along u. So the offset grows by the difference,
    turned into XY; the reference laser's own offset is taken out of
    every laser's, so that it stays 0."""
    reference = machine.geometry.reference_laser
    result = LineUp(reference, edges, used_xy_mm)
    ref = edges.get(reference)
    if ref is None:
        result.error = f"laser {reference} (the reference) was not mapped"
        return result
    for axis in ("u", "v"):
        edge = getattr(ref, axis)
        if edge is None or not edge.trusted:
            result.error = (f"the reference laser's edge along {axis} was "
                            "not found clearly")
            return result
    g = machine.geometry
    ref_used = used_xy_mm.get(reference, (0.0, 0.0))
    for n, e in sorted(edges.items()):
        if n == reference:
            result.proposal[n] = (0.0, 0.0)
            continue
        bad = [axis for axis in ("u", "v")
               if getattr(e, axis) is None or not getattr(e, axis).trusted]
        if bad:
            result.left_out[n] = (
                f"its edge along {' and '.join(bad)} was not found clearly")
            continue
        assert e.u is not None and e.v is not None
        assert ref.u is not None and ref.v is not None
        du = e.u.position_mm - ref.u.position_mm
        dv = e.v.position_mm - ref.v.position_mm
        dx, dy = ab_to_xy(g.x_along, g.y_along, du, dv)
        used = used_xy_mm.get(n, (0.0, 0.0))
        result.proposal[n] = (used[0] - ref_used[0] + dx,
                              used[1] - ref_used[1] + dy)
    return result


def read_lineup(folder: str | Path, machine: MachineConfig) -> LineUp:
    """The line-up from a run's files: every laser's map built again from
    its file, as the run drew it."""
    files = sorted(Path(folder).glob("laser*_*nm.csv"))
    if not files:
        raise LineUpError(f"no laser files in {folder}")
    edges: dict[int, CellEdges] = {}
    used: dict[int, tuple[float, float]] = {}
    for path in files:
        run = read_run(path)
        n = int(run.header["laser"])
        edges[n] = cell_edges(n, build_map(run.scan_data()))
        a, b = run.header.get("cell_offset_xy_mm", (0.0, 0.0))
        used[n] = (float(a), float(b))
    return line_up(edges, used, machine)


_HEADER = re.compile(r"^\s*\[")
_NUMBER = re.compile(r"^\s*number\s*=\s*(\d+)")
_OFFSET = re.compile(r"^(\s*)cell_offset_xy_mm\s*=")


def apply_offsets(text: str, offsets: dict[int, tuple[float, float]],
                  when: str) -> str:
    """machine.toml's text with each laser's `cell_offset_xy_mm` set,
    everything else as it was. Checked by loading the result."""
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if _HEADER.match(line)]
    note = f"  # lineup {when}"
    for k in reversed(range(len(starts))):
        start = starts[k]
        end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        if lines[start].strip() != "[[lasers]]":
            continue
        number = next((int(m.group(1)) for i in range(start, end)
                       if (m := _NUMBER.match(lines[i]))), None)
        if number is None or number not in offsets:
            continue
        x, y = offsets[number]
        value = f"cell_offset_xy_mm = [{x:.3f}, {y:.3f}]{note}\n"
        for i in range(start, end):
            m = _OFFSET.match(lines[i])
            if m:
                lines[i] = m.group(1) + value
                break
        else:
            # After the block's last key, before any blank lines.
            at = end
            while at > start + 1 and not lines[at - 1].strip():
                at -= 1
            lines.insert(at, value)
    out = "".join(lines)
    machine = parse(tomllib.loads(out), "proposed machine.toml")
    for n, xy in offsets.items():
        if not np.allclose(machine.laser(n).cell_offset_xy_mm, xy,
                           atol=6e-4):
            raise LineUpError(
                f"writing laser {n}'s offset went wrong: nothing written")
    return out
