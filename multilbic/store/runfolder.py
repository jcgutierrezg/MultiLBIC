"""
A run folder as one set of maps: what the viewer opens (D30).

A run writes one file per laser (`laser<N>_<nm>nm.csv`), plus `run.json`
(the request, the plans, the outcome) and `calibration.json`. Here every
laser's map is built again from its own file (`scan.mapping`), as
`multilbic map` does, and all of them are put on one grid in the
sample's u, v, so that pixel `[k, j]` is the same spot on the cell for
every laser.

**One grid.** The lasers of a run share the sample frame: each map is
placed on the cell by the photodiode and the line-up's offsets when the
stage moves (D28, D29), so their u and v already mean the same place and
nothing is shifted here. Their grids are then the same, and are used as
they are. Grids that differ (files from different runs, or settings
changed between lasers) are resampled, nearest pixel, onto the finest
pixel and pitch over the area they cover together.

**What's kept from each file**: the laser, its wavelength, whether its
map finished, its range, where it was located on the photodiode, its
alignment and noise floor. A clipped attempt (`laser<N>_<nm>nm_<range>.csv`,
D26) is listed but not mapped; a file that can't be read is listed with
why, and the rest still open.

Reading only: nothing in the folder is written, so a folder can be
opened while its run is still going (its last laser shows the rows
written so far).
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np

from multilbic.config.machine import MachineConfig
from multilbic.scan import eqe as eqe_mod
from multilbic.scan.binning import Grid
from multilbic.scan.mapping import MapResult
from multilbic.store.alignfile import MappedFile, SavedAlignment, map_file

#: A laser's finished map; a clipped attempt has its range after the nm.
LASER_FILE = re.compile(r"^laser(\d+)_(\d+)nm\.csv$")
ATTEMPT_FILE = re.compile(r"^laser(\d+)_(\d+)nm_(.+)\.csv$")


class RunFolderError(Exception):
    """The folder holds no laser maps to open."""


@dataclass(frozen=True)
class SharedGrid:
    """Pixel centres on the sample, mm: `u` along the rows (A), `v`
    across them (B), from the calibration corner."""

    u_mm: np.ndarray
    v_mm: np.ndarray
    pixel_mm: float
    pitch_mm: float

    @property
    def shape(self) -> tuple[int, int]:
        return (self.v_mm.size, self.u_mm.size)

    @property
    def extent_mm(self) -> tuple[float, float, float, float]:
        """(u0, u1, v0, v1): the outer edges of the pixels."""
        return (float(self.u_mm[0] - self.pixel_mm / 2),
                float(self.u_mm[-1] + self.pixel_mm / 2),
                float(self.v_mm[0] - self.pitch_mm / 2),
                float(self.v_mm[-1] + self.pitch_mm / 2))

    @classmethod
    def of(cls, grid: Grid) -> SharedGrid:
        return cls(grid.u_centres, grid.v_centres, grid.pixel_mm,
                   grid.pitch_mm)

    def same_as(self, grid: Grid) -> bool:
        return (grid.values.shape == self.shape
                and math.isclose(grid.pixel_mm, self.pixel_mm)
                and math.isclose(grid.pitch_mm, self.pitch_mm))


@dataclass(frozen=True)
class LaserMap:
    """One laser's map from its file, and the file's header."""

    laser: int
    wavelength_nm: float
    path: Path
    header: dict[str, Any]
    result: MapResult
    #: The map on the run's shared grid, `values[v, u]`, A; NaN where
    #: this laser has no samples.
    values: np.ndarray
    #: The alignment the map was built with, as saved beside the file
    #: (`store/alignfile`).
    saved: SavedAlignment | None = None
    #: Built from that saved alignment rather than searched for.
    reused: bool = False
    #: Why the alignment couldn't be saved, if it couldn't.
    not_saved: str | None = None
    #: The map as EQE (a fraction) on the shared grid, from the power
    #: read before and after it (D31, D32); None without those readings.
    eqe: np.ndarray | None = None
    #: The photodiode's response the EQE rests on.
    response: eqe_mod.Response | None = None
    #: The power over the map, from the photodiode.
    power: eqe_mod.PowerTrack | None = None
    #: Why there is no EQE, if there isn't.
    no_eqe: str | None = None

    @property
    def complete(self) -> bool:
        return self.header.get("status") == "complete"

    @property
    def status(self) -> str:
        return str(self.header.get("status", "?"))

    @property
    def current_range_a(self) -> float | None:
        value = self.header.get("current_range_a")
        return None if value is None else float(value)

    @property
    def located(self) -> dict[str, Any] | None:
        """Where the run found this laser on the photodiode (D29)."""
        return self.header.get("located")

    @property
    def shift_um(self) -> float | None:
        """The serpentine shift the map was aligned by."""
        a = self.result.alignment
        return a.shift_mm * 1000 if a.found else None

    @property
    def noise_a(self) -> float:
        """The dark baseline's spread: the map's noise floor."""
        return self.result.baseline.noise_a

    def label(self) -> str:
        return f"laser {self.laser} ({self.wavelength_nm:g} nm)"


@dataclass(frozen=True)
class Attempt:
    """A map that clipped and was started again one range up (D26)."""

    laser: int
    path: Path
    range_text: str


@dataclass
class RunFolder:
    path: Path
    grid: SharedGrid
    #: By laser number, in order.
    maps: dict[int, LaserMap]
    #: `run.json`, if the folder has one.
    summary: dict[str, Any] | None = None
    #: `calibration.json`, if the folder has one.
    calibration: dict[str, Any] | None = None
    attempts: list[Attempt] = field(default_factory=list)
    #: Files that couldn't be opened, and why.
    problems: dict[str, str] = field(default_factory=dict)
    #: machine.toml as it is now: a response measured since the run.
    machine: MachineConfig | None = None

    @property
    def run_id(self) -> str:
        if self.summary and "run_id" in self.summary:
            return str(self.summary["run_id"])
        return self.path.name

    @property
    def sample(self) -> str:
        for source in (self.summary and self.summary.get("request"),
                       self.calibration, self._any_header()):
            if source and source.get("sample"):
                return str(source["sample"])
        return ""

    @property
    def note(self) -> str:
        request = (self.summary or {}).get("request") or {}
        return str(request.get("note") or self._any_header().get("note") or "")

    @property
    def status(self) -> str:
        """`run.json`'s status, or from the files if there's none."""
        if self.summary and "status" in self.summary:
            return str(self.summary["status"])
        return ("complete" if self.maps and all(m.complete for m in
                                                self.maps.values())
                else "incomplete")

    @property
    def started(self) -> str:
        """When the first laser's map began (ISO time, UTC), or ''."""
        return str(self._any_header().get("started", ""))

    @property
    def simulated(self) -> bool:
        return bool(self._any_header().get("simulated", False))

    @property
    def lasers(self) -> list[int]:
        return list(self.maps)

    def stack(self) -> np.ndarray:
        """Every laser's map, `[laser, v, u]`, in `lasers` order."""
        return np.stack([m.values for m in self.maps.values()])

    def _any_header(self) -> dict[str, Any]:
        for m in self.maps.values():
            return m.header
        return {}


def laser_files(
    folder: Path,
) -> tuple[list[tuple[int, float, Path]], list[Attempt]]:
    """The folder's laser maps as (laser, nm, path) from their names, by
    laser, and its clipped attempts."""
    maps: list[tuple[int, float, Path]] = []
    attempts: list[Attempt] = []
    for path in folder.iterdir():
        if (m := LASER_FILE.match(path.name)) is not None:
            maps.append((int(m.group(1)), float(m.group(2)), path))
        elif (m := ATTEMPT_FILE.match(path.name)) is not None:
            attempts.append(Attempt(int(m.group(1)), path, m.group(3)))
    maps.sort()
    attempts.sort(key=lambda a: (a.laser, a.path.name))
    return maps, attempts


def read_folder(
    folder: str | Path,
    *,
    on_file: Callable[[int, int, Path], None] | None = None,
    by: str = "viewer",
    write: bool = True,
    machine: MachineConfig | None = None,
) -> RunFolder:
    """Every laser's map in `folder`, on one grid. A laser file may be
    given instead of its folder. `on_file(done, total, path)` is called
    before each file, for a progress bar.

    Each map is built from the alignment saved beside its file when
    there is a current one, in about a second; otherwise the alignment
    is searched for and, unless `write` is False, saved for next time
    (`store/alignfile`). `machine` (machine.toml now) gives a
    photodiode response measured since the run, for EQE."""
    folder = Path(folder)
    if folder.is_file():
        folder = folder.parent
    if not folder.is_dir():
        raise RunFolderError(f"{folder}: no such folder")
    files, attempts = laser_files(folder)
    if not files:
        raise RunFolderError(f"{folder}: no laser maps (laser<N>_<nm>nm.csv)")

    built: list[tuple[int, float, Path, MappedFile]] = []
    problems: dict[str, str] = {}
    for k, (named_laser, named_nm, path) in enumerate(files):
        if on_file is not None:
            on_file(k, len(files), path)
        try:
            mapped = map_file(path, by=by, write=write)
        except Exception as exc:  # noqa: BLE001 - one bad file, the rest open
            problems[path.name] = f"{type(exc).__name__}: {exc}"
            continue
        header = mapped.run.header
        laser = int(header.get("laser") or named_laser)
        nm = float(header.get("wavelength_nm") or named_nm)
        built.append((laser, nm, path, mapped))
    if not built:
        raise RunFolderError(
            f"{folder}: none of its laser maps could be read: "
            + "; ".join(f"{name}: {why}" for name, why in problems.items()))

    grid = shared_grid([b[3].result.grid for b in built])
    maps = {
        laser: _laser_map(laser, nm, path, mapped, grid, machine)
        for laser, nm, path, mapped in built
    }
    return RunFolder(
        folder, grid, maps,
        summary=_json(folder / "run.json", problems),
        calibration=_json(folder / "calibration.json", problems),
        attempts=attempts, problems=problems, machine=machine,
    )


def _laser_map(laser: int, nm: float, path: Path, mapped: MappedFile,
               grid: SharedGrid, machine: MachineConfig | None) -> LaserMap:
    header = mapped.run.header
    result = mapped.result
    track = eqe_mod.PowerTrack.from_header(header)
    measured_now: tuple[float | None, str | None] = (None, None)
    if machine is not None and laser in {x.number for x in machine.lasers}:
        spec = machine.laser(laser)
        measured_now = (spec.pd_response_a_w, spec.pd_response_date)
    response = eqe_mod.response_for(header, nm, measured_now)
    eqe = None
    no_eqe = None
    if track is None:
        no_eqe = "no power readings (a run before 0.7.6, or not located)"
    elif response is None:
        no_eqe = f"no photodiode response at {nm:g} nm"
    else:
        times = eqe_mod.row_times(mapped.run.anchors,
                                  result.grid.values.shape[0])
        own = eqe_mod.eqe_map(result.grid.values, times, track, response, nm)
        eqe = on_grid(replace(result.grid, values=own), grid)
    return LaserMap(laser, nm, path, header, result,
                    on_grid(result.grid, grid), mapped.saved,
                    mapped.reused, mapped.not_saved, eqe, response, track,
                    no_eqe)


def rebuild(
    run: RunFolder,
    laser: int,
    *,
    realign: bool = False,
    shift_um: float | None = None,
    by: str = "viewer",
) -> LaserMap:
    """Laser `laser`'s map built again, with its alignment searched for
    afresh (`realign`) or set by hand (`shift_um`), saved, and put in
    `run` in place of the old one, on the same grid."""
    old = run.maps[laser]
    mapped = map_file(old.path, by=by, realign=realign, shift_um=shift_um)
    new = _laser_map(laser, old.wavelength_nm, old.path, mapped, run.grid,
                     run.machine)
    run.maps[laser] = new
    return new


def shared_grid(grids: list[Grid]) -> SharedGrid:
    """The grid every map goes on: the first one's, if all are alike;
    otherwise the finest pixel and pitch over the area they all cover
    between them."""
    first = SharedGrid.of(grids[0])
    if all(first.same_as(g) for g in grids[1:]):
        return first
    pixel = min(g.pixel_mm for g in grids)
    pitch = min(g.pitch_mm for g in grids)
    width = max(g.values.shape[1] * g.pixel_mm for g in grids)
    height = max(g.values.shape[0] * g.pitch_mm for g in grids)
    n_u = max(1, math.ceil(width / pixel - 1e-9))
    n_v = max(1, math.ceil(height / pitch - 1e-9))
    return SharedGrid((np.arange(n_u) + 0.5) * pixel,
                      (np.arange(n_v) + 0.5) * pitch, pixel, pitch)


def on_grid(grid: Grid, shared: SharedGrid) -> np.ndarray:
    """`grid`'s values on `shared`: each shared pixel takes the value of
    the map's pixel its centre falls in, NaN outside the map."""
    if shared.same_as(grid):
        return grid.values.copy()
    n_v, n_u = grid.values.shape
    cols = np.floor(shared.u_mm / grid.pixel_mm).astype(int)
    rows = np.floor(shared.v_mm / grid.pitch_mm).astype(int)
    col_in = (cols >= 0) & (cols < n_u)
    row_in = (rows >= 0) & (rows < n_v)
    out = np.full(shared.shape, np.nan)
    picked = grid.values[np.ix_(rows[row_in], cols[col_in])]
    out[np.ix_(np.flatnonzero(row_in), np.flatnonzero(col_in))] = picked
    return out


def _json(path: Path, problems: dict[str, str]) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        problems[path.name] = f"{type(exc).__name__}: {exc}"
        return None
