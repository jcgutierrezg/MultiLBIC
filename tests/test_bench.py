"""Every bench probe runs end to end against the simulators.

The point is not the numbers, which describe the simulator, but that a
probe never reaches the bench with a typo in a stage nobody had run.
"""

import json

import pytest

from multilbic.bench import laser, marlin, ports, smu


def _report(tmp_path, probe):
    files = list(tmp_path.glob(f"*_{probe}_sim.json"))
    assert len(files) == 1, files
    data = json.loads(files[0].read_text())
    assert data["simulated"] is True
    assert data["probe"] == probe
    assert data["provenance"]["commit"] is None or len(data["provenance"]["commit"]) >= 7
    return data


def test_ports(tmp_path):
    assert ports.main(["--sim", "--out", str(tmp_path)]) == 0
    data = _report(tmp_path, "ports")
    guesses = {row["guess"] for row in data["results"]["ports"]}
    assert "miniSMU" in guesses
    assert "laser board (Xiao)" in guesses


def test_marlin_without_motion(tmp_path):
    assert marlin.main(["--sim", "--out", str(tmp_path)]) == 0
    results = _report(tmp_path, "marlin")["results"]
    assert results["identity"]["machine_type"] == "MultiLBIC"
    assert any("M203" in line for line in results["m503"])
    assert results["m114_round_trip_ms"]["count"] == marlin.ROUND_TRIPS
    assert "move_timing" not in results


def test_marlin_full(tmp_path):
    argv = ["--sim", "--home", "--motion", "--speeds", "3", "--out", str(tmp_path)]
    assert marlin.main(argv) == 0
    results = _report(tmp_path, "marlin")["results"]
    fit = results["move_timing"]["A@2mm/s"]
    assert fit["fitted_speed_mm_s"] == pytest.approx(2.0, rel=0.05)
    assert 0.0 < fit["fixed_overhead_s"] < 1.0
    assert 3.0 < results["stop"]["travelled_mm"] < 4.5
    assert results["keepalive"]["count"] >= 3
    assert results["speeds"][0]["speed_mm_s"] == 3.0


def test_marlin_flags_are_ordered():
    with pytest.raises(SystemExit):
        marlin.main(["--sim", "--motion"])
    with pytest.raises(SystemExit):
        marlin.main(["--sim", "--home", "--speeds", "3"])


def test_laser(tmp_path):
    assert laser.main(["--sim", "--lasers", "--out", str(tmp_path)]) == 0
    results = _report(tmp_path, "laser")["results"]
    switches = results["switches"]
    same_angle = [s for s in switches if not s["servo_moved"]]
    moved = [s for s in switches if s["servo_moved"]]
    assert same_angle and moved
    assert max(s["seconds"] for s in same_angle) < 0.5
    assert min(s["seconds"] for s in moved) > 1.5
    assert results["state_at_end"]["laser"] == 0
    assert results["settle_ms"] == 2000


def test_smu(tmp_path):
    argv = [
        "--sim", "--seconds", "0.5", "--clock-seconds", "2",
        "--noise-seconds", "0.5", "--rates", "100,1000",
        "--out", str(tmp_path),
    ]
    assert smu.main(argv) == 0
    results = _report(tmp_path, "smu")["results"]
    rates = {row["requested_hz"]: row for row in results["rate_sweep"]}
    assert rates[1000.0]["rate_by_device_hz"] == pytest.approx(1000.0, rel=0.01)
    assert rates[100.0]["smallest_step_ms"] == pytest.approx(10.0)
    assert results["dual_channel"]["channel_2"]["samples"] > 0
    assert "drift_ppm" in results["clocks"]
    assert [row["range"] for row in results["noise_0V"]] == [
        "auto", "1uA", "25uA", "650uA",
    ]


def test_smu_real_requires_a_load_description():
    with pytest.raises(SystemExit):
        smu.main(["--real", "--port", "COM99"])
