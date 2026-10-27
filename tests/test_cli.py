"""The command line, end to end against the simulated machine."""

import json

import pytest

from multilbic import cli
from multilbic.clock import ScaledClock
from multilbic.run.devices import sim_corner
from multilbic.sim.rig import Faults, SimRig
from multilbic.sim.sample import SyntheticSample


def saved_calibration(machine, tmp_path, corner=(15.0, 16.0), size=(0.6, 0.2)):
    rig = SimRig(machine, ScaledClock(20.0), SyntheticSample.default(*size),
                 corner, Faults())
    calibration = rig.perfect_calibration("cli cell")
    path = tmp_path / "cal.json"
    path.write_text(json.dumps(
        {"schema": "multilbic-calibration/1", **calibration.to_dict()}
    ))
    return path, calibration, rig


def test_sim_corner_inverts_the_perfect_calibration(machine, tmp_path):
    _, calibration, rig = saved_calibration(machine, tmp_path)
    corner = sim_corner(calibration, machine, Faults())
    assert corner == pytest.approx(rig.corner_carriage_mm)


def test_run_sim_end_to_end(machine, tmp_path, capsys):
    path, _, _ = saved_calibration(machine, tmp_path)
    out = tmp_path / "runs"
    code = cli.main([
        "run", str(path), "--sim", "--yes", "--lasers", "2",
        "--pixel", "0.01", "--pitch", "0.05", "--speed", "2",
        "--baseline", "0.5", "--speedup", "20", "--out", str(out),
        # A short warm-up: at 20x the default 60 s piles up 24,000
        # samples, and on the Pi sorting them outlasted the 0.1 s real
        # (2 s simulated) the stream check allows (2026-10-26). The
        # warm-up itself is tested in test_session.py.
        "--warmup", "1",
    ])
    printed = capsys.readouterr().out
    assert code == 0, printed
    (folder,) = out.iterdir()
    assert folder.name.endswith("_cli-cell")
    names = {p.name for p in folder.iterdir()}
    assert {"run.json", "calibration.json", "events.jsonl",
            "laser2_519nm.csv", "laser2_519nm.png"} <= names
    assert "laser 2: complete" in printed


def test_real_run_refused_until_directions_are_checked(machine, tmp_path):
    from importlib import resources

    path, _, _ = saved_calibration(machine, tmp_path)
    text = (
        resources.files("multilbic.config").joinpath("machine.toml")
        .read_text(encoding="utf-8")
    )
    assert "directions_measured = true" in text
    unchecked = tmp_path / "machine.toml"
    unchecked.write_text(
        text.replace("directions_measured = true",
                     "directions_measured = false"),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="directions_measured"):
        cli.main(["--machine", str(unchecked), "run", str(path), "--yes",
                  "--lasers", "2", "--pixel", "0.01", "--pitch", "0.05"])


def test_bad_requests_are_refused_before_devices(machine, tmp_path):
    path, _, _ = saved_calibration(machine, tmp_path)
    with pytest.raises(SystemExit, match="placeholder"):
        cli.main(["run", str(path), "--sim", "--yes", "--lasers", "5",
                  "--pixel", "0.01", "--pitch", "0.05"])
    with pytest.raises(SystemExit, match="e.g. 1,2,3"):
        cli.main(["run", str(path), "--sim", "--yes", "--lasers", "two",
                  "--pixel", "0.01", "--pitch", "0.05"])


def test_calibrate_sim_with_typed_commands(monkeypatch, tmp_path, capsys):
    lines = iter(["where", "size 2 1", "here", f"save {tmp_path / 'c.json'}",
                  "quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))
    monkeypatch.setattr(cli, "SIM_SPEED", 20.0)
    assert cli.main(["calibrate", "--sim", "--sample", "typed"]) == 0
    saved = json.loads((tmp_path / "c.json").read_text())
    assert saved["sample"] == "typed"
    assert saved["size_mm"] == [2.0, 1.0]
