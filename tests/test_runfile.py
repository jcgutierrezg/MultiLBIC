"""The run file: written row by row, readable at any point."""

import csv

import numpy as np
import pytest

from multilbic.scan.timing import RowAnchor
from multilbic.store.runfile import (
    COLUMNS,
    RunWriter,
    SampleRow,
    read_run,
)

HEADER = {
    "sample": "test: cell 3",
    "laser": 2,
    "frame_origin_ab_mm": [10.0, 11.0],
    "frame_size_mm": [1.0, 0.2],
    "pixel_mm": 0.01,
    "pitch_mm": 0.1,
    "n_rows": 2,
    "mains_hz": 50.0,
    "provenance": {"commit": "abc", "dirty": False},
}


def anchor(index):
    return RowAnchor(index, 11.05 + 0.1 * index, 9.9, 11.1, 1.0, 50.0,
                     100.0 + index, 101.3 + index)


def samples(row, n=3):
    return [
        SampleRow(row, 1 if row >= 0 else 0, 1, 5000.0 + i, 100.5 + i / 1000,
                  1.5e-7 * i, 0.0, 10.0 + i / 1000, 11.05)
        for i in range(n)
    ]


def test_round_trip(tmp_path):
    path = tmp_path / "run.csv"
    writer = RunWriter(path, HEADER)
    writer.write_samples(samples(-1))
    writer.write_row(anchor(0), samples(0))
    writer.write_row(anchor(1), samples(1, n=2))
    writer.finish("complete", {"alignment": {"shift_um": 3.0}})

    run = read_run(path)
    assert run.complete
    assert run.header["sample"] == "test: cell 3"
    assert run.header["provenance"] == {"commit": "abc", "dirty": False}
    assert run.header["alignment"] == {"shift_um": 3.0}
    assert run.anchors == [anchor(0), anchor(1)]
    assert run.columns["row"].tolist() == [-1, -1, -1, 0, 0, 0, 1, 1]
    assert run.columns["current_a"][4] == pytest.approx(1.5e-7)

    data = run.scan_data()
    assert data.frame.origin_ab_mm == (10.0, 11.0)
    assert data.n_rows == 2
    assert data.laser == 2


def test_a_cut_short_run_is_readable_and_says_so(tmp_path):
    path = tmp_path / "run.csv"
    writer = RunWriter(path, HEADER)
    writer.write_row(anchor(0), samples(0))
    # No finish(): the process died here. Everything so far is on disk.
    run = read_run(path)
    assert not run.complete
    assert run.header["status"] == "incomplete"
    assert len(run.anchors) == 1
    assert run.columns["row"].size == 3
    writer.close()


def test_comment_lines_leave_a_plain_table(tmp_path):
    """What pandas.read_csv(path, comment='#') would see."""
    path = tmp_path / "run.csv"
    writer = RunWriter(path, HEADER)
    writer.write_row(anchor(0), samples(0))
    writer.finish("complete", {})
    with path.open(newline="") as f:
        rows = list(csv.reader(line for line in f if not line.startswith("#")))
    assert tuple(rows[0]) == COLUMNS
    assert len(rows) == 4
    assert all(len(r) == len(COLUMNS) for r in rows)


def test_never_overwrites_a_run(tmp_path):
    path = tmp_path / "run.csv"
    RunWriter(path, HEADER).close()
    with pytest.raises(FileExistsError):
        RunWriter(path, HEADER)


def test_raw_timestamps_survive(tmp_path):
    path = tmp_path / "run.csv"
    writer = RunWriter(path, HEADER)
    row = SampleRow(0, 1, 1, 1792513542674.0, 1234.567891, 1e-9, 0.0,
                    17.0, 17.0)
    writer.write_row(anchor(0), [row])
    writer.finish("complete", {})
    run = read_run(path)
    assert run.columns["device_ms"][0] == 1792513542674.0
    assert run.columns["host_s"][0] == pytest.approx(1234.567891, abs=1e-6)
    assert np.isfinite(run.columns["a_mm"]).all()
