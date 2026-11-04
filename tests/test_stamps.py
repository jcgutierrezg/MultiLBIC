"""Dating stream samples by count: the line through saw-toothing stamps,
the stream kept whole between rows, and maps built from it."""

from dataclasses import replace

import numpy as np
import pytest

from multilbic.scan.mapping import GAP_ROW, build_map
from multilbic.scan.stamps import BREAK_MS, date_by_count
from multilbic.sim.rig import Faults
from multilbic.sim.scan import edge_errors, simulate_scan
from multilbic.store.runfile import read_run

PERIOD_MS = 1.25  # 800 Hz


def sawtooth_stamps(n, saw_ms=6.0, every=80, offset_ms=1000.0):
    """Evenly measured samples, stamped as the bench saw: falling behind
    over `every` samples, then jumping back. Whole milliseconds."""
    true = offset_ms + PERIOD_MS * np.arange(n)
    phase = (np.arange(n) % every) / every
    return true, np.round(true + saw_ms * (0.5 - phase))


def test_the_line_through_a_sawtooth_is_the_even_times():
    true, stamps = sawtooth_stamps(2000)
    dated = date_by_count(stamps, np.ones(2000, int))
    # The stamps are up to 3 ms off; the line is within the rounding.
    assert np.max(np.abs(stamps - true)) > 2.5
    assert np.max(np.abs(dated - true)) < 0.6


def test_each_channel_is_dated_on_its_own():
    t1, s1 = sawtooth_stamps(500, offset_ms=0.0)
    t2, s2 = sawtooth_stamps(500, offset_ms=0.4)
    stamps = np.ravel(np.column_stack([s1, s2]))
    channel = np.ravel(np.column_stack([np.ones(500, int),
                                        2 * np.ones(500, int)]))
    dated = date_by_count(stamps, channel)
    assert np.max(np.abs(dated[channel == 1] - t1)) < 0.6
    assert np.max(np.abs(dated[channel == 2] - t2)) < 0.6


def test_a_break_in_the_stream_gets_a_line_each_side():
    true, stamps = sawtooth_stamps(2000)
    # 40 samples lost after the 900th: their time passes, they don't.
    keep = np.r_[0:900, 940:2000]
    dated = date_by_count(stamps[keep], np.ones(keep.size, int))
    assert np.max(np.abs(dated - true[keep])) < 0.6
    # One line over both would have been 25 ms off at the ends.
    one = np.polyval(np.polyfit(np.arange(keep.size), stamps[keep], 1),
                     np.arange(keep.size))
    assert np.max(np.abs(one - true[keep])) > BREAK_MS


def test_a_break_near_the_start_keeps_the_few_samples_before_it():
    # A few samples as the stream starts, then a pause (the simulator's
    # stream does this): the rest still gets its own line.
    true, stamps = sawtooth_stamps(1000)
    stamps = np.r_[stamps[:5] - 425.0, stamps[5:]]
    true = np.r_[true[:5] - 425.0, true[5:]]
    dated = date_by_count(stamps, np.ones(1000, int))
    assert np.array_equal(dated[:5], stamps[:5])
    assert np.max(np.abs(dated[5:] - true[5:])) < 0.6


# ---- in runs ----


def scan(tmp_path, **faults):
    f = replace(Faults(), **faults)
    return simulate_scan(tmp_path, width_mm=1.0, height_mm=0.4,
                         pixel_mm=0.01, pitch_mm=0.05, speed_mm_s=4.0,
                         faults=f)


def test_the_file_keeps_the_stream_between_rows(tmp_path):
    s = scan(tmp_path)
    run = read_run(s.run_path)
    assert run.continuous
    rows = run.columns["row"].astype(int)
    assert (rows == GAP_ROW).sum() > 0
    # Every sample the stream gave is in the file, the last ones too.
    assert rows.size == int(run.header["samples_received"])
    # The gaps' samples are in time order with the rest, and never mapped.
    stamps = run.columns["device_ms"]
    assert np.all(np.diff(stamps[run.columns["channel"] == 1]) > -10)
    grid = build_map(run.scan_data()).grid
    assert grid.values.shape[0] == run.header["n_rows"]


# Measured to a few um: on the Pi's slower cores the simulated scan's
# own timing jitters more than that (2026-11-04).
@pytest.mark.sim_timing
def test_dating_by_count_takes_the_sawtooth_out_of_a_map(tmp_path):
    s = scan(tmp_path, smu_stamp_saw_ms=6.0)
    run = read_run(s.run_path)

    def spread(result):
        found = [e for errs in edge_errors(replace(s, result=result)).values()
                 for e in errs]
        assert len(found) >= 6
        return float(np.std(found))

    by_count = spread(build_map(run.scan_data()))
    by_stamps = spread(build_map(run.scan_data(stamps=True)))
    # 6 ms at 4 mm/s is 24 um peak to peak along a row.
    assert by_stamps > 0.004
    assert by_count < by_stamps / 2


def test_an_old_file_keeps_its_stamps(tmp_path):
    s = scan(tmp_path)
    run = read_run(s.run_path)
    run.header.pop("stream")
    assert not run.continuous
    assert np.array_equal(run.scan_data().device_ms,
                          run.columns["device_ms"])


@pytest.mark.sim_timing
def test_steady_stamps_give_the_same_map_either_way(tmp_path):
    # With no saw-tooth, the count and the stamps agree to the rounding.
    s = scan(tmp_path)
    run = read_run(s.run_path)
    shift = (build_map(run.scan_data()).alignment.shift_mm
             - build_map(run.scan_data(stamps=True)).alignment.shift_mm)
    assert abs(shift) < 0.004
