"""
Phase 3's "done when": a simulated scan recovers the synthetic pattern
within tolerance despite injected latency, backlash and clock drift.

The agreed case (2026-10-20): 5 ms reply latency, 20 µm backlash on A
and B, the SMU clock 100 ppm fast. The agreed tolerances: edges within
5 µm or one pixel, whichever is larger; the forward/reverse shift
estimated within 2 µm of the one present.

It runs at 2x real time with precise sleeps, because at higher factors
the threads' own scheduling delays add latency nobody injected (see
`ScaledClock`). One scan takes about 10 s.
"""

import numpy as np
import pytest

from multilbic.clock import ScaledClock
from multilbic.sim.rig import Faults
from multilbic.sim.scan import (
    edge_errors,
    position_errors,
    simulate_scan,
    v_edge_errors,
)
from multilbic.store.image import save_png
from multilbic.store.runfile import read_run

# The precise clock spin-waits in several threads, which contend for
# Python's GIL. On the Pi's slower cores that delayed the readers by
# several simulated ms (2026-10-21), failing checks of the simulator's
# own timing. Real runs use the real clock and never spin. CI, including
# its ARM runner, runs these.
pytestmark = pytest.mark.sim_timing

PIXEL_MM = 0.005
PITCH_MM = 0.05
SPEED_MM_S = 1.0


@pytest.fixture(scope="module")
def scan(tmp_path_factory):
    return simulate_scan(
        tmp_path_factory.mktemp("scan"),
        width_mm=1.0,
        height_mm=0.4,
        pixel_mm=PIXEL_MM,
        pitch_mm=PITCH_MM,
        speed_mm_s=SPEED_MM_S,
        faults=Faults(),
        clock=ScaledClock(2.0, precise=True),
    )


def test_the_agreed_faults_are_in(scan):
    f = scan.rig.faults
    assert f.reply_latency_s == 0.005
    assert f.backlash_mm == 0.020
    assert f.smu_drift_ppm == 100.0


def test_run_file_is_complete(scan):
    run = read_run(scan.run_path)
    assert run.complete
    assert len(run.anchors) == 8
    assert (run.columns["row"] == -1).sum() > 500  # the dark baseline
    assert run.header["simulated"] is True


def test_every_sample_lands_where_the_stage_was(scan):
    errors = position_errors(scan)
    assert errors.after.size > 2000
    assert np.abs(errors.after).max() < 0.005


def test_shift_is_measured_within_2_um(scan):
    errors = position_errors(scan)
    found = scan.result.alignment
    assert found.found
    assert found.shift_mm == pytest.approx(errors.true_shift_mm, abs=0.002)
    # And the shift really is the injected faults: backlash forward,
    # minus twice the reply latency at the scan speed. The simulator's
    # own scheduling adds a little on top.
    f = scan.rig.faults
    nominal = f.backlash_mm - 2 * SPEED_MM_S * (
        f.reply_latency_s + f.reply_jitter_s / 2
    )
    assert errors.true_shift_mm == pytest.approx(nominal, abs=0.004)


def test_late_replies_dont_move_the_rows(scan, tmp_path):
    """Marlin's `ok` to the M400s coming 30 ms late from mid-map on
    (the bench's late streaks, 2026-11-05): the rows are placed from
    their sends, and the shift and the edges are as without it."""
    executed = scan.rig.fake_marlin.executed
    rows_g1 = [i for i, c in enumerate(executed)
               if c.startswith("G1") and " A" in c
               and c.endswith(f"F{SPEED_MM_S * 60:.3f}")]
    middle = rows_g1[len(rows_g1) // 2]
    after = sum(1 for c in executed[:middle] if c.startswith("M400"))
    late = simulate_scan(
        tmp_path,
        width_mm=1.0,
        height_mm=0.4,
        pixel_mm=PIXEL_MM,
        pitch_mm=PITCH_MM,
        speed_mm_s=SPEED_MM_S,
        faults=Faults(m400_late_s=0.03, m400_late_after=after),
        clock=ScaledClock(2.0, precise=True),
    )
    assert late.rig.fake_marlin.m400_count > after + 2
    found = late.result.alignment
    assert found.found
    assert found.shift_mm == pytest.approx(
        scan.result.alignment.shift_mm, abs=0.004)
    errors = edge_errors(late)
    worst = max(np.abs(e).max() for e in errors.values())
    assert worst <= max(0.005, PIXEL_MM)


def test_a_row_that_starts_late_stays_where_it_was(scan, tmp_path):
    """A single row's G1 taken up 30 ms late: its move and its reply
    both come late (bench, 2026-11-05). Placed from its reply, as its
    neighbours agree, the edges are as without it."""
    executed = scan.rig.fake_marlin.executed
    rows_g1 = [i for i, c in enumerate(executed)
               if c.startswith("G1") and " A" in c
               and c.endswith(f"F{SPEED_MM_S * 60:.3f}")]
    # Every line the board took up, in order: a row's G1 in the middle.
    line = rows_g1[len(rows_g1) // 2] + 1
    late = simulate_scan(
        tmp_path,
        width_mm=1.0,
        height_mm=0.4,
        pixel_mm=PIXEL_MM,
        pitch_mm=PITCH_MM,
        speed_mm_s=SPEED_MM_S,
        faults=Faults(late_lines=(line,), late_line_s=0.03),
        clock=ScaledClock(2.0, precise=True),
    )
    assert late.rig.fake_marlin.lines_received >= line
    errors = edge_errors(late)
    worst = max(np.abs(e).max() for e in errors.values())
    assert worst <= max(0.005, PIXEL_MM)
    assert late.result.alignment.shift_mm == pytest.approx(
        scan.result.alignment.shift_mm, abs=0.004)
    # What an alignment file keeps (store/alignfile) builds the same map
    # again without searching: the shift, and that row placed from its
    # reply.
    assert late.result.late_from_reply
    from multilbic.scan.mapping import build_map

    again = build_map(read_run(late.run_path).scan_data(),
                      alignment=late.result.alignment,
                      late_from_reply=late.result.late_from_reply)
    np.testing.assert_array_equal(again.grid.values, late.result.grid.values)
    assert again.late_from_reply == late.result.late_from_reply


def test_a_edges_within_tolerance(scan):
    tolerance = max(0.005, PIXEL_MM)
    errors = edge_errors(scan)
    assert len(errors) >= 12
    worst = max(np.abs(e).max() for e in errors.values())
    assert worst <= tolerance


def test_b_edges_within_tolerance(scan):
    tolerance = max(0.005, PITCH_MM)
    errors = v_edge_errors(scan)
    assert len(errors) >= 2
    worst = max(np.abs(e).max() for e in errors.values())
    assert worst <= tolerance


def test_clock_map_puts_every_sample_near_its_true_time(scan):
    """The drift itself is not checked here: 100 ppm over this ~20 s run
    is 2 ms, about the scatter a busy CI runner puts on the window
    minima, so the fitted slope can come out either sign (it did, on
    Ubuntu CI). `test_scan_timing.py` checks drift on a long synthetic
    stream. What matters for the map is that no sample is placed further
    off in time than the edge tolerance allows: 5 ms is 5 µm at 1 mm/s.
    A constant part of the error is removed by the alignment anyway."""
    rig = scan.rig
    stamps = np.concatenate([row.device_ms for row in scan.result.rows])
    mapped = scan.result.clock.to_host(stamps)
    true = np.array([rig.fake_smu.true_time(float(s)) for s in stamps])
    error_s = mapped - true
    assert np.abs(error_s).max() < 0.005 / SPEED_MM_S


def test_map_shows_the_pattern(scan, tmp_path):
    grid = scan.result.grid
    assert grid.values.shape == (8, 200)
    # Laser 3 (652 nm) favours the left cell.
    middle = grid.values[3]
    left = np.nanmedian(middle[30:40])
    right = np.nanmedian(middle[160:175])
    gap = np.nanmedian(middle[97:103])
    # The gap is not zero: slow drift is left in (D8, set aside).
    assert left > right > gap + 0.3e-6
    png = save_png(scan.result, tmp_path / "map.png", title="test")
    assert png.stat().st_size > 1000
