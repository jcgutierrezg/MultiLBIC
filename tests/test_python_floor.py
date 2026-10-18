"""requires-python, .python-version and the CI matrix agree.

Three places name the Python version and nothing ties them together. If
they drift, CI tests one version while the Pi installs another, and the
green tick describes neither.
"""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _floor():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    match = re.fullmatch(r">=(\d+\.\d+)", project["project"]["requires-python"])
    assert match, "requires-python should be a plain '>=X.Y' floor"
    return match.group(1)


def test_python_version_file_matches_floor():
    assert (ROOT / ".python-version").read_text().strip() == _floor()


def test_ci_matrix_tests_the_floor():
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text()
    versions = re.findall(r'python(?:-version)?: \[?"(\d+\.\d+)"', workflow)
    assert versions, "no Python version found in tests.yml"
    assert set(versions) == {_floor()}, versions


def test_tool_targets_match_floor():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    floor = _floor()
    assert project["tool"]["mypy"]["python_version"] == floor
    assert project["tool"]["ruff"]["target-version"] == "py" + floor.replace(
        ".", ""
    )
