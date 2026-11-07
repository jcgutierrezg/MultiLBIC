"""
The run file: one CSV per laser map, written as the run goes.

Layout, following SMUniversal's `#`-header convention, so that
`pandas.read_csv(path, comment="#")` returns the plain sample table:

    # MultiLBIC run
    # schema: multilbic-run/1
    # key: value                 (one per line; values are JSON)
    # status: incomplete
    row,direction,channel,device_ms,host_s,current_a,voltage_v,a_mm,b_mm
    <baseline samples, row -1>
    #row: {"index": 0, ...}      (the row's anchor)
    <that row's samples>
    ...
    # status: complete           (the trailer, after the last row)
    # clock_map: {...}

**Appended and flushed after every row** (D1), so a Stop or a crash
leaves every finished row readable. Nothing is rewritten in place: what
is only known at the end (status, clock map, alignment, baseline) goes
into a trailer of the same `# key: value` lines, and the reader lets a
later key override an earlier one. A file whose last status is
`incomplete` was cut short.

**Raw first.** Every sample keeps the instrument's timestamp and its
host arrival time, and each row its anchor, so a map can be rebuilt
from scratch (`multilbic.scan.mapping`). `a_mm` and `b_mm` are the
positions as mapped when the row was written, before the serpentine
alignment, for a quick look; the map is never built from them.

One line per streamed packet. The two channels stream separate packets,
so a channel column keeps them apart instead of pairing them up.
"""

from __future__ import annotations

import csv
import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

import numpy as np

from multilbic.scan.geometry import SampleFrame
from multilbic.scan.mapping import ScanData
from multilbic.scan.timing import BENCH_ROW_REPLY_S, RowAnchor

SCHEMA = "multilbic-run/1"
TITLE = "# MultiLBIC run"
COLUMNS = (
    "row", "direction", "channel", "device_ms", "host_s",
    "current_a", "voltage_v", "a_mm", "b_mm",
)
ROW_PREFIX = "#row: "


@dataclass(frozen=True)
class SampleRow:
    row: int
    direction: int
    channel: int
    device_ms: float
    host_s: float
    current_a: float
    voltage_v: float
    a_mm: float
    b_mm: float


def _format(row: SampleRow) -> list[str]:
    return [
        str(row.row), str(row.direction), str(row.channel),
        f"{row.device_ms:.0f}", f"{row.host_s:.6f}",
        f"{row.current_a:.6e}", f"{row.voltage_v:.4e}",
        f"{row.a_mm:.6f}", f"{row.b_mm:.6f}",
    ]


def _value(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value)


class RunWriter:
    def __init__(self, path: str | Path, header: dict[str, Any]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file: IO[str] = self.path.open("x", newline="", encoding="utf-8")
        self._csv = csv.writer(self._file, lineterminator="\n")
        lines = [TITLE, f"# schema: {SCHEMA}"]
        lines += [f"# {key}: {_value(v)}" for key, v in header.items()]
        lines.append("# status: incomplete")
        self._file.write("\n".join(lines) + "\n")
        self._csv.writerow(COLUMNS)
        self._flush()

    def write_samples(self, samples: list[SampleRow]) -> None:
        self._csv.writerows(_format(s) for s in samples)
        self._flush()

    def write_row(self, anchor: RowAnchor, samples: list[SampleRow]) -> None:
        self._file.write(
            ROW_PREFIX + json.dumps(dataclasses.asdict(anchor)) + "\n"
        )
        self.write_samples(samples)

    def note(self, entries: dict[str, Any]) -> None:
        """`# key: value` lines here, between rows: what is learnt as the
        map goes (the power before it, D31). The reader takes them as it
        takes the header, a later key over an earlier one."""
        lines = [f"# {key}: {_value(v)}" for key, v in entries.items()]
        self._file.write("\n".join(lines) + "\n")
        self._flush()

    def finish(self, status: str, trailer: dict[str, Any]) -> None:
        lines = [f"# status: {status}"]
        lines += [f"# {key}: {_value(v)}" for key, v in trailer.items()]
        self._file.write("\n".join(lines) + "\n")
        self._flush()
        self.close()

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()

    def _flush(self) -> None:
        self._file.flush()


@dataclass
class RunFile:
    header: dict[str, Any]
    anchors: list[RowAnchor]
    columns: dict[str, np.ndarray]

    @property
    def complete(self) -> bool:
        return self.header.get("status") == "complete"

    @property
    def continuous(self) -> bool:
        """Every sample the stream gave is in the file, in order (since
        0.6.35): they can be dated by count (`scan.stamps`)."""
        return self.header.get("stream") == "continuous"

    def scan_data(self, *, stamps: bool = False) -> ScanData:
        """The map's data. A continuous stream's samples are dated by
        their count, not by the instrument's saw-toothing stamps
        (`scan.stamps`); `stamps` keeps the stamps, to compare."""
        h = self.header
        origin = tuple(h["frame_origin_ab_mm"])
        width, height = h["frame_size_mm"]
        c = self.columns
        device_ms = c["device_ms"]
        if self.continuous and not stamps:
            from multilbic.scan.stamps import date_by_count

            device_ms = date_by_count(device_ms, c["channel"].astype(int))
        return ScanData(
            frame=SampleFrame((origin[0], origin[1]), width, height),
            pixel_mm=h["pixel_mm"],
            pitch_mm=h["pitch_mm"],
            n_rows=h["n_rows"],
            mains_hz=h["mains_hz"],
            anchors=tuple(self.anchors),
            row=c["row"].astype(int),
            channel=c["channel"].astype(int),
            device_ms=device_ms,
            host_s=c["host_s"],
            current_a=c["current_a"],
            laser=h.get("laser", 0),
            ab_backlash_mm=h.get("ab_backlash_mm", 0.0),
            row_reply_s=h.get("row_reply_ms", BENCH_ROW_REPLY_S * 1000) / 1000,
        )


def _parse_value(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def read_run(path: str | Path) -> RunFile:
    """The file's header, row anchors and sample columns.

    The numbers are parsed by numpy's C reader (`np.loadtxt`), not line
    by line in Python: a 120 MB file in about 1.3 s on the PC instead of
    2.9 s, to the same values. A last line cut short, as a file being
    written can have, is left out."""
    header: dict[str, Any] = {}
    anchors: list[RowAnchor] = []
    data: list[str] = []
    names: list[str] | None = None
    with Path(path).open(newline="", encoding="utf-8") as f:
        lines = f.read().splitlines()
    for line in lines:
        if not line:
            continue
        if line[0] == "#":
            if line.startswith(ROW_PREFIX):
                anchors.append(RowAnchor(**json.loads(line[len(ROW_PREFIX):])))
            else:
                key, sep, value = line[1:].strip().partition(":")
                if sep:
                    header[key.strip()] = _parse_value(value.strip())
        elif names is None:
            names = next(csv.reader([line]))
        else:
            data.append(line)
    if names is None:
        raise ValueError(f"{path}: no column header")
    if header.get("schema") != SCHEMA:
        raise ValueError(f"{path}: schema {header.get('schema')!r}, "
                         f"expected {SCHEMA}")
    if data and data[-1].count(",") != len(names) - 1:
        data.pop()
    table = (np.loadtxt(data, delimiter=",", dtype=float, ndmin=2)
             if data else np.empty((0, len(names))))
    columns = {name: table[:, i] for i, name in enumerate(names)}
    return RunFile(header, anchors, columns)
