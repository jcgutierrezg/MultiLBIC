"""
A laser map's alignment, saved beside its file (D30, revised).

Building a map searches for the serpentine shift (`scan/alignment`) and,
for rows whose replies came late, for the placement their neighbours
agree with. On a full-size map that is nearly all the time it takes: 20
of 23 s for an 18 x 20 mm map on the PC. Both answers are saved in
`laser<N>_<nm>nm.align.json` next to `laser<N>_<nm>nm.csv`, and the map
is built from them in about a second.

    {"schema": "multilbic-align/1", "laser_file": "laser6_848nm.csv",
     "file_bytes": 119236407, "rows": 400,
     "alignment": {"shift_um": 149.3, "quality": 0.59, ...},
     "late_from_reply": [101, 119], "how": "computed", "by": "run",
     "app_version": "0.7.4", "made": "2026-11-07T10:12:00+00:00"}

**Who writes it**: the run, as each laser's map ends; anything that maps
a file without one (the viewer, `multilbic map`, the window's "Open run
file"); and the viewer's **Re-align** (searched again with the code as
it is now) and **Set shift** (a shift typed by hand: `how` "by hand").

**When it is not used**: the file has changed size or row count since
(a run still going, or a file replaced): the map is built afresh and the
alignment saved again. A file that can't be read is ignored the same
way. One that can't be written (a read-only folder) leaves the map as
built: it just isn't saved.

The line-up and the sync check search afresh every time: they are
measurements, and a shift set by hand is not theirs to take.
"""

from __future__ import annotations

import datetime
import json
import math
import os
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from multilbic.scan.alignment import Alignment
from multilbic.scan.mapping import MapResult, build_map
from multilbic.store.runfile import RunFile, read_run
from multilbic.version import app_version

SCHEMA = "multilbic-align/1"
SUFFIX = ".align.json"
COMPUTED = "computed"
BY_HAND = "by hand"


class NoRows(ValueError):
    """A laser file with no rows yet (a run stopped before its first):
    nothing to map."""


def path_for(laser_file: str | Path) -> Path:
    """`laser6_848nm.csv` -> `laser6_848nm.align.json`, beside it."""
    p = Path(laser_file)
    return p.with_name(p.stem + SUFFIX)


@dataclass(frozen=True)
class SavedAlignment:
    alignment: Alignment
    late_from_reply: tuple[int, ...]
    #: COMPUTED or BY_HAND.
    how: str
    #: What wrote it: "run", "viewer", "map", "window".
    by: str
    app_version: str
    #: ISO time, UTC.
    made: str
    #: The laser file's size and row count it was made for.
    file_bytes: int
    rows: int

    @property
    def by_hand(self) -> bool:
        return self.how == BY_HAND

    def describe(self) -> str:
        """'shift 149.3 µm (quality 0.59), computed by the run, 0.7.4,
        2026-11-07 10:12 UTC'."""
        a = self.alignment
        if not a.found:
            what = "no shift found"
        elif self.by_hand:
            what = f"shift {a.shift_mm * 1000:.1f} µm"
        else:
            what = f"shift {a.shift_mm * 1000:.1f} µm (quality {a.quality:.2f})"
        when = self.made
        try:
            when = datetime.datetime.fromisoformat(self.made).strftime(
                "%Y-%m-%d %H:%M UTC")
        except ValueError:
            pass
        who = {"run": "the run", "viewer": "the viewer",
               "map": "multilbic map", "window": "the window"}.get(
                   self.by, self.by)
        return f"{what}, {self.how} by {who}, {self.app_version}, {when}"

    def to_dict(self, laser_file: str) -> dict[str, Any]:
        a = self.alignment
        return {
            "schema": SCHEMA,
            "laser_file": laser_file,
            "file_bytes": self.file_bytes,
            "rows": self.rows,
            "alignment": {
                "shift_um": a.shift_mm * 1000,
                "quality": a.quality if math.isfinite(a.quality) else None,
                "pairs": a.pairs,
                "found": a.found,
                "smooth_um": a.smooth_mm * 1000,
            },
            "late_from_reply": list(self.late_from_reply),
            "how": self.how,
            "by": self.by,
            "app_version": self.app_version,
            "made": self.made,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SavedAlignment:
        if d.get("schema") != SCHEMA:
            raise ValueError(f"schema {d.get('schema')!r}, expected {SCHEMA}")
        a = d["alignment"]
        quality = a.get("quality")
        return cls(
            Alignment(
                shift_mm=float(a["shift_um"]) / 1000,
                quality=float("nan") if quality is None else float(quality),
                pairs=int(a.get("pairs", 0)),
                found=bool(a["found"]),
                smooth_mm=float(a.get("smooth_um", 0.0)) / 1000,
            ),
            tuple(int(k) for k in d.get("late_from_reply", ())),
            str(d.get("how", COMPUTED)),
            str(d.get("by", "?")),
            str(d.get("app_version", "?")),
            str(d.get("made", "")),
            int(d["file_bytes"]),
            int(d["rows"]),
        )


def by_hand_alignment(shift_um: float) -> Alignment:
    """A shift typed by hand: found, with no correlation behind it."""
    return Alignment(shift_um / 1000, float("nan"), 0, True, 0.0)


def load(laser_file: str | Path, rows: int | None = None
         ) -> SavedAlignment | None:
    """The saved alignment, if there is one made for the file as it is
    now (same size, and `rows` anchors when given); None otherwise."""
    laser_file = Path(laser_file)
    path = path_for(laser_file)
    try:
        saved = SavedAlignment.from_dict(
            json.loads(path.read_text(encoding="utf-8")))
        size = laser_file.stat().st_size
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if saved.file_bytes != size or (rows is not None and saved.rows != rows):
        return None
    return saved


def save(laser_file: str | Path, saved: SavedAlignment) -> Path:
    """Written whole or not at all (a temporary file, then renamed)."""
    laser_file = Path(laser_file)
    path = path_for(laser_file)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(saved.to_dict(laser_file.name), indent=1) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)
    return path


def _record(laser_file: Path, run: RunFile, result: MapResult, *, how: str,
            by: str) -> SavedAlignment:
    return SavedAlignment(
        result.alignment, result.late_from_reply, how, by, app_version(),
        datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        laser_file.stat().st_size, len(run.anchors))


@dataclass(frozen=True)
class MappedFile:
    run: RunFile
    result: MapResult
    saved: SavedAlignment
    #: Built from a saved alignment, not searched for.
    reused: bool
    #: Why the alignment wasn't saved, if it wasn't.
    not_saved: str | None = None


def map_file(
    laser_file: str | Path,
    *,
    by: str,
    realign: bool = False,
    shift_um: float | None = None,
    write: bool = True,
) -> MappedFile:
    """A laser file's map, from its saved alignment when there is a
    current one; otherwise searched for, and saved. `realign` searches
    again whatever is saved; `shift_um` sets the shift by hand (the late
    rows are kept as saved, or searched for if nothing is)."""
    laser_file = Path(laser_file)
    run = read_run(laser_file)
    if not run.anchors:
        raise NoRows(f"{laser_file.name}: no rows yet")
    data = run.scan_data()
    saved = None if realign else load(laser_file, rows=len(run.anchors))
    late: Collection[int] | None = saved.late_from_reply if saved else None
    if shift_um is not None:
        result = build_map(data, alignment=by_hand_alignment(shift_um),
                           late_from_reply=late)
        how, reused = BY_HAND, False
    elif saved is not None:
        result = build_map(data, alignment=saved.alignment,
                           late_from_reply=late)
        return MappedFile(run, result, saved, reused=True)
    else:
        result = build_map(data)
        how, reused = COMPUTED, False
    record = _record(laser_file, run, result, how=how, by=by)
    not_saved = None
    if write:
        try:
            save(laser_file, record)
        except OSError as exc:
            not_saved = f"{type(exc).__name__}: {exc}"
    return MappedFile(run, result, record, reused, not_saved)
