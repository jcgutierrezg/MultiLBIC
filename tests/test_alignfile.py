"""A laser map's alignment saved beside its file: written by the run,
reused when the file hasn't changed, searched again on request, or set
by hand."""

import json
import math
import shutil

import numpy as np
import pytest

from multilbic.scan.mapping import build_map
from multilbic.store import alignfile
from multilbic.store.alignfile import (
    BY_HAND,
    COMPUTED,
    NoRows,
    SavedAlignment,
    by_hand_alignment,
    map_file,
    path_for,
)
from multilbic.store.runfile import read_run


@pytest.fixture
def laser_file(run_folder, tmp_path):
    """Laser 1's file in a copy of the simulated run, so tests can
    change its alignment."""
    folder = shutil.copytree(run_folder, tmp_path / run_folder.name)
    return next(folder.glob("laser1_*nm.csv"))


def test_the_run_saves_each_lasers_alignment(run_folder):
    for csv in sorted(run_folder.glob("laser*_*nm.csv")):
        saved = alignfile.load(csv)
        assert saved is not None, csv.name
        assert (saved.how, saved.by) == (COMPUTED, "run")
        fresh = build_map(read_run(csv).scan_data())
        assert saved.alignment.shift_mm == pytest.approx(
            fresh.alignment.shift_mm)
        assert saved.late_from_reply == fresh.late_from_reply
    assert path_for(csv).name == csv.stem + ".align.json"


def test_a_saved_alignment_builds_the_same_map(laser_file):
    first = map_file(laser_file, by="viewer")
    assert first.reused  # saved by the run
    fresh = build_map(read_run(laser_file).scan_data())
    np.testing.assert_array_equal(first.result.grid.values,
                                  fresh.grid.values)


def test_a_changed_file_is_aligned_again(laser_file):
    with laser_file.open("a", encoding="utf-8") as f:
        f.write("# note: appended\n")
    mapped = map_file(laser_file, by="viewer")
    assert not mapped.reused
    assert mapped.saved.by == "viewer"
    # Saved again for the file as it is now.
    assert map_file(laser_file, by="viewer").reused


def test_realign_searches_again_and_saves(laser_file):
    mapped = map_file(laser_file, by="viewer", realign=True)
    assert not mapped.reused
    assert (mapped.saved.how, mapped.saved.by) == (COMPUTED, "viewer")
    assert alignfile.load(laser_file).by == "viewer"


def test_a_shift_set_by_hand_is_kept(laser_file):
    computed = map_file(laser_file, by="viewer").result
    mapped = map_file(laser_file, by="viewer", shift_um=37.5)
    assert mapped.saved.by_hand and mapped.saved.how == BY_HAND
    assert mapped.result.alignment.shift_mm == pytest.approx(0.0375)
    assert not np.array_equal(mapped.result.grid.values,
                              computed.grid.values, equal_nan=True)
    again = map_file(laser_file, by="viewer")
    assert again.reused and again.saved.by_hand
    assert again.result.alignment.shift_mm == pytest.approx(0.0375)
    np.testing.assert_array_equal(again.result.grid.values,
                                  mapped.result.grid.values)
    assert "by hand" in again.saved.describe()
    # Re-align puts a searched one back.
    assert not map_file(laser_file, by="viewer",
                        realign=True).saved.by_hand


def test_a_broken_file_is_ignored_and_replaced(laser_file):
    path_for(laser_file).write_text("{not json", encoding="utf-8")
    assert alignfile.load(laser_file) is None
    mapped = map_file(laser_file, by="viewer")
    assert not mapped.reused and mapped.not_saved is None
    assert alignfile.load(laser_file) is not None


def test_an_unwritable_folder_still_maps(laser_file, monkeypatch):
    def refuse(*args, **kwargs):
        raise PermissionError("read-only")

    monkeypatch.setattr(alignfile, "save", refuse)
    mapped = map_file(laser_file, by="viewer", realign=True)
    assert mapped.result.grid.values.size
    assert "read-only" in mapped.not_saved


def test_it_round_trips_through_json():
    saved = SavedAlignment(by_hand_alignment(-12.5), (3, 7), BY_HAND,
                           "viewer", "0.7.4", "2026-11-07T10:00:00+00:00",
                           1234, 40)
    d = json.loads(json.dumps(saved.to_dict("laser1_444nm.csv")))
    assert d["alignment"]["quality"] is None  # NaN isn't JSON
    back = SavedAlignment.from_dict(d)
    assert back.alignment.shift_mm == pytest.approx(-0.0125)
    assert math.isnan(back.alignment.quality) and back.alignment.found
    assert back.late_from_reply == (3, 7)
    assert back.describe().startswith("shift -12.5 µm, by hand by the viewer")
    with pytest.raises(ValueError, match="schema"):
        SavedAlignment.from_dict({**d, "schema": "other/1"})


def test_a_file_with_no_rows_has_nothing_to_map(laser_file):
    lines = laser_file.read_text(encoding="utf-8").splitlines(keepends=True)
    first_row = next(k for k, line in enumerate(lines)
                     if line.startswith("#row: "))
    laser_file.write_text("".join(lines[:first_row]), encoding="utf-8")
    with pytest.raises(NoRows):
        map_file(laser_file, by="viewer")
