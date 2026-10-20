"""The Pi deployment scripts: syntax, and the USB boot check's logic.

The boot check (`deploy/pi/usb-check.sh`) runs against a fake by-id
folder and a fake `uhubctl` that records its calls and, like a real
power cycle, can make a missing Xiao reappear.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PI = ROOT / "deploy" / "pi"
BASH = shutil.which("bash")

pytestmark = [
    pytest.mark.skipif(BASH is None, reason="needs bash"),
    pytest.mark.skipif(
        sys.platform == "win32",
        reason="the scripts target the Pi; run on Linux CI",
    ),
]

XIAO = "usb-Seeed_Seeed_XIAO_M0_AC5401405154315432202020FF102436-if00"
SKR = "usb-marlinfw.org_Marlin_USB_Device_1602400395D510E961DB1B78F50020C1-if00"


@pytest.mark.parametrize("script", sorted(PI.glob("*.sh")), ids=lambda p: p.name)
def test_scripts_parse(script):
    subprocess.run([BASH, "-n", str(script)], check=True)


def _fake_uhubctl(bin_dir: Path, byid: Path, revive: bool) -> Path:
    """A uhubctl that logs its arguments; 'on' brings the Xiao back if
    `revive`, as a real power cycle does for a stuck board."""
    calls = bin_dir / "calls.log"
    revive_line = f'touch "{byid}/{XIAO}"' if revive else ":"
    script = bin_dir / "uhubctl"
    script.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> "{calls}"\n'
        f'if [[ "$*" == *"-a on"* ]]; then {revive_line}; fi\n'
    )
    script.chmod(0o755)
    return calls


def _run(tmp_path, *, xiao_there: bool, revive: bool, args=()):
    byid = tmp_path / "by-id"
    byid.mkdir()
    (byid / SKR).touch()
    if xiao_there:
        (byid / XIAO).touch()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = _fake_uhubctl(bin_dir, byid, revive)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "MULTILBIC_BYID_DIR": str(byid),
        "MULTILBIC_WAIT_AT_BOOT_S": "1",
        "MULTILBIC_WAIT_AFTER_CYCLE_S": "2",
        "MULTILBIC_POWER_OFF_S": "0",
    }
    result = subprocess.run(
        [BASH, str(PI / "usb-check.sh"), *args],
        env=env, capture_output=True, text=True, timeout=30,
    )
    cycled = calls.read_text().splitlines() if calls.exists() else []
    return result, cycled


def test_present_xiao_is_left_alone(tmp_path):
    result, cycled = _run(tmp_path, xiao_there=True, revive=False)
    assert result.returncode == 0
    assert "Xiao present; others: SKR" in result.stdout
    assert cycled == []


def test_missing_xiao_is_recovered_by_a_power_cycle(tmp_path):
    result, cycled = _run(tmp_path, xiao_there=False, revive=True)
    assert result.returncode == 0
    assert "cycling USB power" in result.stdout
    assert "Xiao present after USB power cycle" in result.stdout
    # Both hubs off, then both on: the Pi 4's ports share one switch.
    assert cycled == [
        "-l 2 -a off", "-l 1-1 -a off", "-l 1-1 -a on", "-l 2 -a on",
    ]


def test_still_missing_after_the_cycle_fails_loudly(tmp_path):
    result, cycled = _run(tmp_path, xiao_there=False, revive=False)
    assert result.returncode == 1
    assert "still missing" in result.stdout
    assert len(cycled) == 4


def test_force_cycles_even_when_present(tmp_path):
    result, cycled = _run(
        tmp_path, xiao_there=True, revive=True, args=("--force",)
    )
    assert result.returncode == 0
    assert "forced USB power cycle (Xiao present: yes)" in result.stdout
    assert len(cycled) == 4
