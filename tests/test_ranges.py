"""A sample's current ranges, checked at calibration (D25)."""

import json
import threading
import time

import pytest

from multilbic.run.calibrate import Calibrator, load_calibration, load_ranges
from multilbic.run.motion import RunStopped
from multilbic.run.ranges import (
    RangeCheck,
    check_duration_s,
    check_result,
    choose_range,
    grid_lines,
    near_top,
    ranges_from_dict,
    ranges_to_dict,
)
from multilbic.run.rows import ScanDevices
from multilbic.scan.geometry import SampleFrame
from multilbic.sim.rig import Faults, SimRig
from multilbic.sim.sample import SyntheticSample

# ---- the choice, the grid, the record ----


def test_the_range_holds_three_times_the_brightest_reading():
    # The test cell on the bench: laser 2 ~0.7 uA, lasers 1 and 3 60-80 uA.
    assert choose_range(0.7e-6) == 25e-6
    assert choose_range(80e-6) == 650e-6
    assert choose_range(0.3e-6) == 1e-6
    assert choose_range(0.34e-6) == 25e-6  # 3x is past 1 uA
    assert choose_range(1.0) == 180e-3  # nothing holds it: the largest


def test_a_reading_at_the_checks_limit_means_maybe_brighter():
    seen = check_result(1, [0.5e-3, 0.99e-3], bias_v=0.0)
    assert seen.at_limit and seen.range_a == 15e-3
    fine = check_result(2, [0.2e-6, -0.7e-6], bias_v=0.0)
    assert not fine.at_limit and fine.peak_a == 0.7e-6
    assert fine.range_a == 25e-6 and fine.readings == 2
    with pytest.raises(ValueError, match="no readings"):
        check_result(3, [], bias_v=0.0)


def test_the_grid_crosses_the_sample_three_times_each_way():
    frame = SampleFrame((10.0, 20.0), 6.0, 3.0)
    lines = grid_lines(frame)
    assert len(lines) == 6
    along_a = [ln for ln in lines if ln[0][1] == ln[1][1]]
    along_b = [ln for ln in lines if ln[0][0] == ln[1][0]]
    assert sorted(ln[0][1] for ln in along_a) == pytest.approx([20.5, 21.5,
                                                               22.5])
    assert sorted(ln[0][0] for ln in along_b) == pytest.approx([11.0, 13.0,
                                                               15.0])
    # Each spans the whole sample; alternate lines run back.
    for (a0, b0), (a1, b1) in lines:
        assert {a0, a1} <= {10.0, 16.0} or {b0, b1} <= {20.0, 23.0}
    assert lines[0][0][0] < lines[0][1][0] and lines[1][0][0] > lines[1][1][0]
    # 3 x 6 mm + 3 x 3 mm = 27 mm of lines at 2 mm/s, plus the
    # overhead, per laser.
    assert check_duration_s(frame, 2) == pytest.approx(2 * (13.5 + 8.0))


def test_a_reading_at_a_ranges_top_is_not_trusted():
    assert near_top(24e-6) == 25e-6
    assert near_top(26.8e-6) == 25e-6  # a range reads a little past its end
    assert near_top(0.9e-6) == 1e-6
    assert near_top(600e-6) == 650e-6
    assert near_top(10e-6) is None and near_top(2.3e-6) is None
    assert near_top(92.7e-6) is None
    # The check's own 1 mA limit is `at_limit`'s business, not this.
    assert near_top(14e-3) is None


def test_checks_survive_a_round_trip():
    checks = {2: RangeCheck(2, 0.7e-6, 25e-6, 0.0, "2026-10-27T12:00:00+00:00",
                            480),
              1: RangeCheck(1, 1e-3, 15e-3, 0.5, "2026-10-27T12:01:00+00:00",
                            450, at_limit=True),
              3: RangeCheck(3, 97e-6, 650e-6, 0.0, "2026-10-27T12:02:00+00:00",
                            900, autorange_top_a=25e-6)}
    data = json.loads(json.dumps(ranges_to_dict(checks)))
    assert list(data) == ["1", "2", "3"]
    assert "autorange_top_a" not in data["1"]
    assert ranges_from_dict(data) == checks
    assert ranges_from_dict(None) == {}


# ---- on the simulated machine ----


def calibrator(machine, clock, cell_a=1e-6):
    rig = SimRig(machine, clock, SyntheticSample.default(2.0, 1.0,
                                                         cell_a=cell_a),
                 (15.2, 16.1), Faults())
    rig.open()
    cal = Calibrator(ScanDevices(rig.marlin, rig.laser, rig.smu), machine,
                     sample="cell", clock=clock)
    truth = rig.perfect_calibration("cell")
    cal.start(check=truth)
    return rig, cal


@pytest.mark.parametrize(("cell_a", "expected"), [(1e-6, 25e-6),
                                                   (1e-4, 650e-6)])
def test_checking_ranges_on_the_sample(machine, clock, tmp_path, cell_a,
                                       expected):
    rig, cal = calibrator(machine, clock, cell_a)
    said = []
    cal.say = said.append
    try:
        checked = cal.check_ranges([3, 2])
    finally:
        rig.close()
    assert set(checked) == {2, 3} and cal.ranges == checked
    # Each grid line is in the log, with what it read.
    lines = [s for s in said if s.startswith("  line ")]
    # (A 1 uA cell peaks at 0.9 uA, near the 1 uA range's top: its
    # grid is read again on 25 uA.)
    assert len(lines) in (12, 18, 24) and all("readings" in s for s in lines)
    for result in checked.values():
        assert result.range_a == expected
        assert result.readings >= 20 and not result.at_limit
        assert result.peak_a * 3 <= result.range_a
    # Ends as it began: the reference laser on the corner.
    assert rig.fake_laser.active == machine.geometry.reference_laser
    u, v = rig.spot_uv(rig.fake_marlin.stage_position(),
                       machine.geometry.reference_laser)
    assert (u, v) == pytest.approx((0.0, 0.0), abs=1e-3)
    # Saved with the calibration and read back.
    path = cal.save(tmp_path / "cell.json")
    assert load_ranges(path) == checked
    assert load_calibration(path).corner_xy_mm == cal.corner_xy


def test_autorange_stuck_at_a_ranges_top_is_read_again(machine, clock):
    # The cell gives ~100 uA, but autorange stays on 25 uA (simulated:
    # not seen on the real one, 2026-10-27).
    rig, cal = calibrator(machine, clock, cell_a=1e-4)
    rig.fake_smu.autorange_stuck = 1  # 25 uA
    said = []
    cal.say = said.append
    try:
        checked = cal.check_ranges([2])
        after = (rig.fake_smu.autorange[1], rig.fake_smu.enabled[1])
    finally:
        rig.close()
    result = checked[2]
    assert result.autorange_top_a == 25e-6
    assert result.peak_a > 30e-6 and result.range_a == 650e-6
    assert not result.at_limit
    assert any("reading the grid again on 650 uA" in s for s in said)
    # Two grids in the log, and back on autorange with the output on.
    assert len([s for s in said if s.startswith("  line ")]) == 12
    assert after == (True, True)


def test_an_older_calibration_file_has_no_ranges(machine, clock, tmp_path):
    rig, cal = calibrator(machine, clock)
    rig.close()
    path = cal.save(tmp_path / "old.json")
    assert "current_ranges" not in json.loads(path.read_text())
    assert load_ranges(path) == {}


def test_halt_stops_a_range_check(machine, clock):
    rig, cal = calibrator(machine, clock)
    said = []
    cal.say = said.append
    caught = []

    def work():
        try:
            cal.check_ranges([2, 3])
        except RunStopped as exc:
            caught.append(exc)

    worker = threading.Thread(target=work)
    try:
        worker.start()
        deadline = time.monotonic() + 30
        while not any("checking laser" in s for s in said):
            assert time.monotonic() < deadline
            time.sleep(0.005)
        time.sleep(0.02)
        cal.halt()
        worker.join(30)
    finally:
        rig.close()
    assert caught and not worker.is_alive()
    assert cal.ranges == {}  # nothing half-checked is kept
    assert not rig.fake_marlin.moving()


def test_calibrate_prompt_checks_ranges(machine, clock, tmp_path):
    from multilbic.run.calibrate import CalibrationPrompt

    rig = SimRig(machine, clock, SyntheticSample.default(2.0, 1.0),
                 (15.2, 16.1), Faults())
    rig.open()
    truth = rig.perfect_calibration("cell")
    lines = ["ranges 2", f"save {tmp_path / 'cal.json'}", "quit"]
    out = []
    prompt = CalibrationPrompt(
        ScanDevices(rig.marlin, rig.laser, rig.smu), machine, sample="cell",
        read=lambda p: lines.pop(0) if lines else (_ for _ in ()).throw(
            EOFError()),
        write=out.append, clock=clock)
    try:
        prompt.start(check=truth)
        prompt.loop()
    finally:
        rig.close()
    assert not [line for line in out if line.startswith("error")], out
    assert any(line.startswith("ranges: 2=25uA") for line in out)
    assert load_ranges(tmp_path / "cal.json")[2].range_a == 25e-6


def test_run_uses_the_checked_ranges(machine, tmp_path, capsys):
    """Without --current-range, `run` maps each laser with the range its
    calibration checked; --current-range overrides it."""
    from multilbic import cli

    rig = SimRig(machine, clock_for_cli(), SyntheticSample.default(0.6, 0.2),
                 (15.0, 16.0), Faults())
    calibration = rig.perfect_calibration("cli cell")
    checks = {2: RangeCheck(2, 0.2e-3, 650e-6, 0.0,
                            "2026-10-27T12:00:00+00:00", 100)}
    path = tmp_path / "cal.json"
    path.write_text(json.dumps({"schema": "multilbic-calibration/1",
                                **calibration.to_dict(),
                                "current_ranges": ranges_to_dict(checks)}))
    common = ["run", str(path), "--sim", "--yes", "--lasers", "2",
              "--pixel", "0.01", "--pitch", "0.05", "--speed", "2",
              "--baseline", "0.5", "--speedup", "20", "--warmup", "1"]
    for extra, expected, says in (([], 650e-6, "(checked 2026-10-27)"),
                                  (["--current-range", "25u"], 25e-6, "")):
        out = tmp_path / f"runs{len(extra)}"
        assert cli.main([*common, "--out", str(out), *extra]) == 0
        printed = capsys.readouterr().out
        assert says in printed
        (folder,) = out.iterdir()
        summary = json.loads((folder / "run.json").read_text())
        assert summary["plans"][0]["current_range_a"] == expected


def clock_for_cli():
    from multilbic.clock import ScaledClock

    return ScaledClock(20.0)
