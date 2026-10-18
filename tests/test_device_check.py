"""The device check script runs end to end against the simulators."""

from multilbic.hardware import check


def test_sim_check_passes(capsys):
    assert check.main(["--sim", "--home", "--move", "--lasers"]) == 0
    out = capsys.readouterr().out
    assert out.count("PASS") == 3
    assert "all devices answered" in out


def test_move_without_home_fails_cleanly(capsys):
    assert check.main(["--sim", "--move"]) == 1
    assert "--move needs --home" in capsys.readouterr().out
