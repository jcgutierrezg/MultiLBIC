"""`multilbic read`: one SMU channel, dark and under lasers, no motion."""

import json
import threading

import pytest

from multilbic import cli
from multilbic.run.devices import open_sim
from multilbic.run.reading import (
    ChannelReading,
    ReadStopped,
    read_channel,
    summarise,
)


def sim(machine, channels=(2,)):
    return open_sim(machine, speed=50.0, smu_channels=channels)


def test_summary_and_limit():
    r = summarise(1, [1e-6, 2e-6, 3e-6])
    assert r.median_a == pytest.approx(2e-6)
    assert r.mean_a == pytest.approx(2e-6)
    assert r.peak_a == pytest.approx(3e-6)
    assert r.outliers == 0
    assert not r.at_limit
    assert summarise(1, [-0.99e-3]).at_limit
    assert summarise(1, [-0.99e-3], limit_a=15e-3).at_limit is False
    with pytest.raises(ValueError):
        summarise(1, [])


def test_an_autorange_spike_is_left_out():
    # Bench, 2026-10-29: laser 3 near -0.5 mA, one reading of +6.2 mA.
    values = [-0.5e-3 + i * 2e-6 for i in range(-25, 25)] + [6.18e-3]
    r = summarise(3, values)
    assert r.outliers == 1
    assert r.median_a == pytest.approx(-0.5e-3, abs=3e-6)
    assert r.mean_a == pytest.approx(-0.501e-3, abs=3e-6)
    assert r.max_a < 0
    assert not r.at_limit
    assert len(r.as_dict()["values_a"]) == 51


def test_a_quiet_dark_has_no_outliers():
    r = summarise(0, [16.03e-9] * 40 + [16.05e-9, 15.99e-9])
    assert r.outliers == 0


def test_net_sign_and_range():
    result = ChannelReading(2, 0.0, summarise(0, [1e-9, 0.0, -1e-9]),
                            {3: summarise(3, [-50e-6, -51e-6, -52e-6])})
    assert result.net_a(3) == pytest.approx(-51e-6)
    assert result.range_a(3) == pytest.approx(650e-6)
    lines = result.lines()
    assert "negative" in lines[1]
    assert not any("hardly shows" in line for line in lines)


def test_a_laser_that_hardly_shows_is_flagged():
    result = ChannelReading(2, 0.0, summarise(0, [0.0, 1e-9, 2e-9]),
                            {1: summarise(1, [1e-9, 2e-9, 3e-9])})
    assert any("hardly shows" in line for line in result.lines())


def test_reads_dark_then_each_laser_and_switches_everything_off(machine):
    conn = sim(machine)
    try:
        result = read_channel(conn.devices, machine, conn.clock,
                              lasers=[1, 3], read_s=0.2, settle_s=0.1,
                              say=lambda _: None)
        rig = conn.rig
        assert rig is not None
        assert abs(result.dark.mean_a) < 1e-6
        for n in (1, 3):
            assert result.net_a(n) == pytest.approx(rig.photodiode_lit_a,
                                                    rel=0.05)
        assert rig.fake_laser.active == 0
        assert not rig.fake_smu.enabled[2]
        # Channel 1 (the cell) was never switched on.
        assert not rig.fake_smu.enabled[1]
    finally:
        conn.close()


def test_refuses_a_channel_not_opened_and_unknown_lasers(machine):
    conn = sim(machine, channels=(1,))
    try:
        with pytest.raises(ValueError, match="channels"):
            read_channel(conn.devices, machine, conn.clock, channel=2)
        with pytest.raises(KeyError):
            read_channel(conn.devices, machine, conn.clock, channel=1,
                         lasers=[9])
        assert conn.rig is not None and conn.rig.fake_laser.active == 0
    finally:
        conn.close()


def test_stop_switches_off(machine):
    conn = sim(machine)
    stop = threading.Event()
    stop.set()
    try:
        with pytest.raises(ReadStopped):
            read_channel(conn.devices, machine, conn.clock, lasers=[1],
                         stop=stop, say=lambda _: None)
        rig = conn.rig
        assert rig is not None
        assert rig.fake_laser.active == 0
        assert not rig.fake_smu.enabled[2]
    finally:
        conn.close()


def test_cli_read_sim_saves(tmp_path, capsys):
    out = tmp_path / "read.json"
    code = cli.main(["read", "--sim", "--lasers", "2", "--seconds", "0.2",
                     "--settle", "0.1", "--speedup", "50", "--out", str(out)])
    assert code == 0
    text = capsys.readouterr().out
    assert "dark" in text and "laser 2:" in text
    data = json.loads(out.read_text())
    assert data["schema"] == "multilbic-read/1"
    assert data["channel"] == 2
    assert data["lasers"]["2"]["net_a"] > 30e-6


def test_cli_read_refuses_unknown_laser():
    with pytest.raises(SystemExit, match="no laser 9"):
        cli.main(["read", "--sim", "--lasers", "9"])


def test_cli_read_on_a_fixed_range(tmp_path, capsys):
    out = tmp_path / "read.json"
    assert cli.main(["read", "--sim", "--lasers", "1", "--seconds", "0.2",
                     "--settle", "0.1", "--speedup", "50",
                     "--current-range", "15m", "--out", str(out)]) == 0
    assert "15 mA range" in capsys.readouterr().out
    data = json.loads(out.read_text())
    assert data["current_range_a"] == pytest.approx(15e-3)
    assert data["lasers"]["1"]["limit_a"] == pytest.approx(15e-3)
    with pytest.raises(SystemExit, match="no range '7u'"):
        cli.main(["read", "--sim", "--current-range", "7u"])


def test_places_home_and_move_and_ranges_get_their_own_dark(machine):
    conn = sim(machine)
    places = {1: (90.0, 70.0, 30.0, 19.0), 3: (88.0, 75.0, 28.0, 8.0)}
    try:
        result = read_channel(conn.devices, machine, conn.clock,
                              lasers=[1, 3], read_s=0.1, settle_s=0.05,
                              ranges={3: 15e-3}, places=places,
                              say=lambda _: None)
        rig = conn.rig
        assert rig is not None
        assert result.places == places
        assert 3 in result.darks and 1 not in result.darks
        assert result.range_of(3) == pytest.approx(15e-3)
        assert result.range_of(1) is None
        assert result.lit[3].limit_a == pytest.approx(15e-3)
        at = conn.devices.marlin.position()
        assert [at[k] for k in "XYAB"] == pytest.approx(
            [88.0, 75.0, 28.0, 8.0], abs=1e-6)
        data = result.as_dict()
        assert data["lasers"]["3"]["xyab_mm"] == list(places[3])
        assert "dark" in data["lasers"]["3"]
        assert rig.fake_laser.active == 0
    finally:
        conn.close()


def test_no_places_no_motion(machine):
    conn = sim(machine)
    try:
        read_channel(conn.devices, machine, conn.clock, lasers=[2],
                     read_s=0.1, settle_s=0.05, say=lambda _: None)
        assert not conn.devices.marlin.position_trusted
    finally:
        conn.close()


def test_cli_places_and_ranges_are_checked():
    with pytest.raises(SystemExit, match="laser=X,Y,A,B"):
        cli.main(["read", "--sim", "--lasers", "1", "--at", "1=100,70"])
    with pytest.raises(SystemExit, match="not in --lasers"):
        cli.main(["read", "--sim", "--lasers", "1",
                  "--at", "2=100,70,30,10"])
    with pytest.raises(SystemExit, match="not in --lasers"):
        cli.main(["read", "--sim", "--lasers", "1",
                  "--current-range", "3=15m"])
