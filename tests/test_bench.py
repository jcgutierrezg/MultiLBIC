"""Every bench probe runs end to end against the simulators.

The point is not the numbers, which describe the simulator, but that a
probe never reaches the bench with a typo in a stage nobody had run.
"""

import dataclasses
import json

import pytest

from multilbic.bench import laser, laser_module, marlin, ports, smu


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


def test_marlin_speed_trial_on_b_moves_only_b(tmp_path):
    # --speeds needs only --home; --speed-axis b moves B and nothing else.
    argv = [
        "--sim", "--home", "--speeds", "4", "--speed-axis", "b",
        "--out", str(tmp_path),
    ]
    assert marlin.main(argv) == 0
    results = _report(tmp_path, "marlin")["results"]
    assert "move_timing" not in results
    row = results["speeds"][0]
    assert row["axis"] == "B" and row["speed_mm_s"] == 4.0
    # Every timed move is a full 20 mm at 4 mm/s: model 5.08 s plus the
    # first-move delay.
    assert row["move_s"]["min"] > 5.0
    sent = " ".join(results["traffic_tail"])
    assert "G1 A" not in sent.split("M203 A4 B4")[-1]


def test_marlin_flags_are_ordered():
    with pytest.raises(SystemExit):
        marlin.main(["--sim", "--motion"])
    with pytest.raises(SystemExit):
        marlin.main(["--sim", "--speeds", "3"])


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


def _responses(monkeypatch, response):
    """Every laser's power-meter response set to `response` (None for
    uncalibrated), whatever machine.toml holds today."""
    real_setup = laser_module.setup

    def setup(args):
        machine, clock = real_setup(args)
        lasers = tuple(
            dataclasses.replace(
                laser, pd_response_a_w=response,
                pd_response_date=response and "2026-11-10",
            )
            for laser in machine.lasers
        )
        return dataclasses.replace(machine, lasers=lasers), clock

    monkeypatch.setattr(laser_module, "setup", setup)


def _module(tmp_path, *extra):
    argv = [
        "--sim", "--hold-s", "3", "--no-plot", "--out", str(tmp_path), *extra,
    ]
    assert laser_module.main(argv) == 0
    return _report(tmp_path, "laser_module")["results"]


def _assert_within_ceilings(results):
    ceilings = results["ceilings"]
    dark = results["dark"]["pd_a"]["mean"]
    for p in laser_module._every_reading(results):
        assert p["set"] >= 0
        assert p["v"] <= laser_module.MAX_V * 1.01
        assert abs(p["i"]) <= ceilings["current_a"] * 1.01
        if ceilings["light_pd_a"] is not None:
            assert abs(p["pd"] - dark) <= ceilings["light_pd_a"] * 1.01


@pytest.mark.parametrize(
    "module", ["regulated", "resistor", "starved", "rollover", "laser4"])
def test_laser_module_stays_within_the_ceilings(tmp_path, module):
    results = _module(tmp_path, "--module", module)
    assert "stopped" not in results
    assert {"current", "voltage", "hold"} <= results.keys()
    _assert_within_ceilings(results)


def test_laser_module_finds_a_regulator(tmp_path):
    results = _module(tmp_path, "--module", "regulated")
    judged = results["judged_current"]
    assert judged["kind"] == "regulated"
    assert judged["i_reg_a"] == pytest.approx(0.028, rel=0.02)
    assert judged["threshold_a"] == pytest.approx(0.016, abs=0.001)
    assert judged["kinks"] == 0
    held = results["judged_hold"]
    assert held["constant_voltage"] and held["constant_current"]
    assert any("Regulated inside" in line for line in results["verdict"])


def test_laser_module_finds_a_starved_regulator_above_todays_point(tmp_path):
    # Today's point says nothing about the limit: the sweep goes past
    # today's current to find the regulator at 35 mA.
    results = _module(tmp_path, "--module", "starved", "--v-known", "4.5")
    judged = results["judged_current"]
    assert judged["kind"] == "regulated"
    assert judged["i_reg_a"] == pytest.approx(0.035, rel=0.02)
    assert judged["v_reg"] > 4.5
    assert judged["i_max_a"] > 1.2 * results["ceilings"]["light_by_a"] / 1.5


def test_laser_module_without_a_regulator_stops_at_the_light_ceiling(tmp_path):
    results = _module(tmp_path, "--module", "resistor")
    assert results["current"]["stopped_by"] == "light ceiling"
    assert results["judged_current"]["kind"] == "no regulator reached"


def test_laser_module_stops_when_the_curve_bends(tmp_path):
    results = _module(tmp_path, "--module", "rollover")
    assert results["current"]["stopped_by"] == "curve bending"
    light_cap = results["ceilings"]["light_pd_a"]
    assert results["judged_current"]["peak_light_a"] < 0.5 * light_cap


def test_laser_module_reads_light_past_1_ma(tmp_path, monkeypatch):
    # Laser 4's first run: autoranging, the miniSMU held the photodiode
    # to 1 mA, the light read flat and "curve bending" stopped it. On the
    # fixed 15 mA range it reaches its light ceiling.
    _responses(monkeypatch, 0.4559)
    results = _module(tmp_path, "--module", "laser4", "--i-known", "23m")
    assert results["dark"]["pd_range_a"] == laser_module.PD_LIMIT_A
    assert results["current"]["stopped_by"] == "light ceiling"
    judged = results["judged_current"]
    assert judged["peak_light_a"] > 1.5e-3
    assert judged["threshold_a"] == pytest.approx(0.0165, abs=0.001)
    # The holds are on the lasing part of the curve, not below threshold.
    assert results["operating_point"]["a"] > 0.0165 + 0.002
    held = results["judged_hold"]
    assert held["constant_current"] is not None


def test_laser_module_operating_point_is_on_the_light():
    up = [
        {"set": i, "i": i, "v": 2.0 + 25 * i, "pd": -max(0.0, i - 0.0165) * 0.25,
         "why": ""}
        for i in (0.0, 0.005, 0.010, 0.015, 0.0165, 0.018, 0.019, 0.020, 0.0205)
    ]
    i_op, v_op, i_max = laser_module.operating_point(up)
    assert i_max == 0.0205
    assert i_op == pytest.approx(0.0165 + 0.8 * 0.004)
    assert v_op == pytest.approx(2.0 + 25 * i_op)
    # No light (the dummy load): 80 % of the highest current.
    dark = [dict(p, pd=0.0) for p in up]
    assert laser_module.operating_point(dark)[0] == pytest.approx(0.8 * 0.0205)


@pytest.mark.parametrize("offset_a, says", [
    (297e-6, "with the laser off"),     # laser 4's second run
    (-8e-6, "the dark isn't steady"),   # small, and the dangerous sign
])
def test_laser_module_refuses_a_bad_dark(tmp_path, monkeypatch, offset_a, says):
    from multilbic.sim.laser_module import FakeModuleSMU

    monkeypatch.setattr(FakeModuleSMU, "PD_OFFSET_A", offset_a)
    monkeypatch.setattr(FakeModuleSMU, "PD_OFFSET_READS", 20)
    results = _module(tmp_path, "--module", "laser4", "--i-known", "23m")
    assert says in results["stopped"]
    up = results.get("current", {}).get("up", [])
    assert max((p["i"] for p in up), default=0.0) < 1e-4


def test_laser_module_stops_without_light(tmp_path):
    # Today's current says the laser lights by 1 mA; at 1.5 mA nothing:
    # the beam is not on the photodiode, so nothing goes higher.
    results = _module(tmp_path, "--module", "regulated", "--i-known", "1m")
    assert "no light" in results["stopped"]
    assert max(p["i"] for p in results.get("current", {}).get("up", [])
               or [{"i": 0}]) <= 1.6e-3


def test_laser_module_dry_run_on_a_resistor(tmp_path):
    results = _module(tmp_path, "--dummy-load")
    assert "stopped" not in results
    assert results["dummy_load"] is True
    assert results["current"]["stopped_by"] == "voltage limit"
    _assert_within_ceilings(results)
    assert any("the limits held" in line for line in results["verdict"])


def test_laser_module_light_ceiling_from_the_datasheet(tmp_path, monkeypatch):
    _responses(monkeypatch, None)
    results = _module(tmp_path, "--module", "regulated", "--max-mw", "2")
    ceilings = results["ceilings"]
    assert ceilings["response_from"] == "S1223-01 datasheet"
    expected = laser_module.MARGIN_DATASHEET * 2e-3 * ceilings["pd_response_a_w"]
    assert ceilings["light_pd_a"] == pytest.approx(expected)


def test_laser_module_light_ceiling_from_the_power_meter(tmp_path, monkeypatch):
    _responses(monkeypatch, 0.44)
    results = _module(tmp_path, "--module", "regulated", "--max-mw", "2")
    ceilings = results["ceilings"]
    assert ceilings["response_from"] == "power meter 2026-11-10"
    expected = laser_module.MARGIN_CALIBRATED * 2e-3 * 0.44
    assert ceilings["light_pd_a"] == pytest.approx(expected)


def test_laser_module_datasheet_overrides_the_power_meter(tmp_path, monkeypatch):
    _responses(monkeypatch, 0.44)
    results = _module(tmp_path, "--module", "regulated", "--datasheet-response")
    assert results["ceilings"]["response_from"] == "S1223-01 datasheet"


def test_laser_module_polarity_check(capsys):
    assert laser_module.main(["--sim", "--polarity-check"]) == 0
    out = capsys.readouterr().out
    assert "+1.000 V" in out and "Channel 1 off." in out


def test_laser_module_refuses_unsafe_arguments(monkeypatch):
    _responses(monkeypatch, None)
    monkeypatch.setattr(
        "builtins.input", lambda *a: pytest.fail("got as far as asking"))
    real = ["--real", "--port", "COM99"]
    for extra in (
        ["--laser", "3"],                                    # no --i-known
        ["--i-known", "30m"],                                # no --laser
        ["--laser", "3", "--i-known", "30m"],                # no power-meter response
        ["--laser", "3", "--i-known", "30m", "--datasheet-response", "--max-mw", "6"],
        ["--laser", "3", "--i-known", "30m", "--datasheet-response", "--max-ma", "150"],
        ["--laser", "3", "--i-known", "30m", "--datasheet-response", "--v-known", "6"],
        ["--dummy-load", "--laser", "3", "--i-known", "20m"],
    ):
        with pytest.raises(SystemExit):
            laser_module.main(real + extra)


def test_parse_amps():
    assert laser_module.parse_amps("32m") == pytest.approx(0.032)
    assert laser_module.parse_amps("32 mA") == pytest.approx(0.032)
    assert laser_module.parse_amps("0.032") == pytest.approx(0.032)
    assert laser_module.parse_amps("500u") == pytest.approx(5e-4)
