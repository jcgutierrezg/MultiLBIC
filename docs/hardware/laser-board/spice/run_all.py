"""Runs every .cir here in LTspice's batch mode and prints what each measured.

    python run_all.py            all runs
    python run_all.py 05 08      only those whose names start so

LTspice is looked for in its usual places, or at the path in the
LTSPICE environment variable. Its .log and .raw files stay beside the
netlists (they are git-ignored).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
PLACES = [
    os.environ.get("LTSPICE", ""),
    r"C:\Program Files\ADI\LTspice\LTspice.exe",
    str(Path.home() / r"AppData\Local\Programs\ADI\LTspice\LTspice.exe"),
]


def ltspice() -> str:
    for place in PLACES:
        if place and Path(place).is_file():
            return place
    sys.exit("LTspice.exe not found: set LTSPICE to its path")


def measurements(log: Path) -> tuple[list[str], dict[str, list[str]]]:
    """The steps' settings, and each measurement's value per step."""
    text = log.read_text(encoding="utf-8", errors="replace")
    steps = re.findall(r"^\.step (.*)$", text, re.M)
    out: dict[str, list[str]] = {}
    name = None
    for line in text.splitlines():
        m = re.match(r"Measurement: (\S+)", line)
        failed = re.match(r'Measurement "(\S+)" FAIL', line)
        if failed:
            out[failed.group(1)] = ["failed"]
            name = None
        elif m:
            name = m.group(1)
            out[name] = []
        elif name and re.match(r"\s+\d+\t", line):
            out[name].append(line.split("\t")[1].strip())
        elif name and line.strip() and not line.startswith("  step"):
            # an unstepped run: "name: MAX(v(x))=1.23 FROM 0 TO 1"
            name = None
    for m in re.finditer(r"^(\w+): .*?=(\S+)", text, re.M):
        out.setdefault(m.group(1), [m.group(2)])
    return steps, out


def short(value: str) -> str:
    try:
        return f"{float(value):.4g}"
    except ValueError:
        m = re.match(r"\(([-0-9.e+]+)dB,([-0-9.e+]+)", value)
        if m:
            return f"{float(m.group(1)):.1f} dB, {float(m.group(2)):.1f} deg"
        return value


def main() -> int:
    exe = ltspice()
    wanted = sys.argv[1:]
    bad = 0
    for cir in sorted(HERE.glob("*.cir")):
        if wanted and not any(cir.name.startswith(w) for w in wanted):
            continue
        log = cir.with_suffix(".log")
        log.unlink(missing_ok=True)
        # LTspice itself, on a netlist from this folder.
        subprocess.run([exe, "-b", cir.name], cwd=HERE, check=False,  # noqa: S603
                       timeout=600)
        print(f"\n== {cir.name}")
        if not log.exists():
            print("   no log: LTspice did not run it")
            bad += 1
            continue
        steps, meas = measurements(log)
        if not meas:
            print("   nothing measured: see", log.name)
            bad += 1
        for i, s in enumerate(steps, 1):
            print(f"   step {i}: {s}")
        for name, values in meas.items():
            print(f"   {name:24s} " + " | ".join(short(v) for v in values))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
