"""The machine file loads, matches docs/hardware.md, and refuses nonsense."""

import copy
import dataclasses
import tomllib
from importlib import resources

import pytest

from multilbic.config import MachineConfigError, load
from multilbic.config.machine import parse


@pytest.fixture
def raw():
    """The packaged machine.toml as a dict, to break one key at a time."""
    text = (
        resources.files("multilbic.config")
        .joinpath("machine.toml")
        .read_text(encoding="utf-8")
    )
    return tomllib.loads(text)


def test_default_loads():
    config = load()
    assert config.name == "MultiLBIC"
    assert [laser.number for laser in config.lasers] == [1, 2, 3, 4, 5, 6]


def test_values_match_hardware_notes():
    config = load()
    # Laser 2 is the alignment laser; its position was measured.
    laser2 = config.laser(2)
    assert laser2.wavelength_nm == 519
    assert laser2.xy_centre_mm == (75.6, 71.7)
    assert laser2.measured
    # Two groups of three share servo angles.
    for a, b in [(1, 4), (2, 5), (3, 6)]:
        assert (
            config.laser(a).servo_angle_deg
            == config.laser(b).servo_angle_deg
        )
    # 4, 5 and 6 are placeholders until commissioning.
    assert [laser.measured for laser in config.lasers] == [
        True, True, True, False, False, False,
    ]
    assert config.ab.centre_mm == (17.5, 17.5)
    assert config.ab.max_feed_mm_s == 6.0
    assert config.ab.microstep_mm == pytest.approx(0.3125e-3)


def test_loads_from_a_path(tmp_path):
    text = (
        resources.files("multilbic.config")
        .joinpath("machine.toml")
        .read_text(encoding="utf-8")
    )
    path = tmp_path / "machine.toml"
    path.write_text(text.replace('"MultiLBIC"', '"Bench copy"'))
    assert load(path).name == "Bench copy"


def test_config_is_immutable():
    config = load()
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.ab.safe_max_mm = 40.0  # type: ignore[misc]


def test_ports_by_platform():
    config = load()
    assert config.ports("linux").skr.startswith("/dev/serial/by-id/")
    assert "1602400395D510E961DB1B78F50020C1" in config.ports("linux").skr
    assert config.ports("win32").skr == ""
    # A platform with no entry gets empty ports rather than an error.
    assert config.ports("darwin").laser == ""


def test_unknown_laser_number():
    with pytest.raises(KeyError):
        load().laser(7)


def test_bad_toml_names_the_file(tmp_path):
    path = tmp_path / "broken.toml"
    path.write_text("name = ")
    with pytest.raises(MachineConfigError, match="broken.toml"):
        load(path)


def _breaks(raw, mutate, match):
    data = copy.deepcopy(raw)
    mutate(data)
    with pytest.raises(MachineConfigError, match=match):
        parse(data)


def test_misspelt_key_is_refused(raw):
    def mutate(d):
        d["ab"]["safe_max"] = d["ab"].pop("safe_max_mm")

    # Reported as missing first: the real key is gone.
    _breaks(raw, mutate, "safe_max_mm")


def test_extra_key_is_refused(raw):
    _breaks(raw, lambda d: d["ab"].update(speed=3), "unknown key")


def test_extra_top_level_key_is_refused(raw):
    _breaks(raw, lambda d: d.update(colour="red"), "unknown key")


def test_safe_range_beyond_travel(raw):
    _breaks(raw, lambda d: d["ab"].update(safe_max_mm=41.0), "safe range")


def test_inverted_safe_range(raw):
    _breaks(raw, lambda d: d["ab"].update(safe_min_mm=36.0), "safe range")


def test_centre_outside_safe_range(raw):
    _breaks(
        raw, lambda d: d["ab"].update(centre_mm=[17.5, 36.0]), "centre_mm"
    )


def test_duplicate_laser(raw):
    _breaks(
        raw,
        lambda d: d["lasers"][5].update(number=5),
        "more than once",
    )


def test_laser_number_out_of_range(raw):
    _breaks(raw, lambda d: d["lasers"][0].update(number=7), "not one of")


def test_servo_angle_out_of_range(raw):
    _breaks(
        raw,
        lambda d: d["lasers"][0].update(servo_angle_deg=200),
        "servo_angle_deg",
    )


def test_bool_is_not_a_number(raw):
    _breaks(
        raw, lambda d: d["lasers"][0].update(number=True), "integer"
    )


def test_pair_needs_two_numbers(raw):
    _breaks(
        raw,
        lambda d: d["lasers"][0].update(xy_centre_mm=[1.0]),
        "two numbers",
    )


def test_negative_feed(raw):
    _breaks(
        raw, lambda d: d["ab"].update(max_feed_mm_s=-1), "positive"
    )


def test_no_lasers(raw):
    _breaks(raw, lambda d: d.update(lasers=[]), "no \\[\\[lasers\\]\\]")


def test_laser_board_settle(raw):
    assert load().laser_board.settle_ms == 2000
    _breaks(
        raw,
        lambda d: d["laser_board"].update(settle_ms=20000),
        "settle_ms",
    )


def test_geometry_defaults(machine):
    g = machine.geometry
    assert g.reference_laser == 2
    assert (g.x_along, g.y_along) == ("+A", "+B")
    # Checked on the bench 2026-10-21 (docs/hardware.md, Mechanics).
    assert g.directions_measured
    assert g.ab_backlash_mm == 0.0


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("x_along", "A", "not one of"),
        ("y_along", "-A", "same AB axis"),
        ("reference_laser", 9, "not defined"),
        ("ab_backlash_mm", 0.5, "below ab_take_up_mm"),
        ("ab_backlash_mm", -0.01, ">= 0"),
        ("xy_take_up_mm", 0.0, "xy_take_up_mm"),
    ],
)
def test_geometry_refuses_impossible_values(raw, key, value, message):
    raw["geometry"][key] = value
    with pytest.raises(MachineConfigError, match=message):
        parse(raw)


def test_display_matches_the_operators_view(machine):
    # Bench, 2026-10-23: rows run from the right edge leftwards and
    # step downwards, as the operator sees the cell.
    assert machine.display.view == ("left", "down")


@pytest.mark.parametrize(
    ("u", "v", "message"),
    [("sideways", "down", "not one of"), ("left", "right", "right angles")],
)
def test_display_refuses_impossible_views(raw, u, v, message):
    raw["display"] = {"u_points": u, "v_points": v}
    with pytest.raises(MachineConfigError, match=message):
        parse(raw)
