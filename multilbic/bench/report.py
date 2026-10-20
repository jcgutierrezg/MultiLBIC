"""
The report every bench probe writes, and the plumbing they share.

A report is a dict that ends up as one JSON file. It records where it
came from (commit, dirty tree, version, host, simulated or not, the
arguments) as well as what was measured, so a number quoted in
`docs/hardware.md` can always be traced back to the code and firmware
that produced it. SMUniversal found out the hard way what a report that
doesn't name its commit costs.
"""

from __future__ import annotations

import argparse
import datetime
import json
import platform
import statistics
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any

from multilbic.clock import SYSTEM_CLOCK, Clock, ScaledClock
from multilbic.config import load
from multilbic.config.machine import MachineConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "bench-results"
#: Simulated probes run this much faster than real time.
SIM_SPEED = 20.0  # see tests/conftest.py for why not faster


def say(text: str = "") -> None:
    print(text, flush=True)


def summary(values: list[float]) -> dict[str, float | int | None]:
    """count, mean, stdev, min, median, max of a list of numbers."""
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else None,
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
    }


def linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Least-squares slope and intercept of y = slope * x + intercept."""
    slope, intercept = statistics.linear_regression(xs, ys)
    return slope, intercept


def base_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument(
        "--sim", action="store_true", help="run against the simulators"
    )
    where.add_argument(
        "--real", action="store_true", help="run against the machine"
    )
    parser.add_argument(
        "--machine", default=None, help="machine.toml (default: packaged)"
    )
    parser.add_argument(
        "--out", default=str(DEFAULT_OUT), help="folder for the JSON report"
    )
    return parser


def setup(args) -> tuple[MachineConfig, Clock]:
    machine = load(args.machine)
    clock: Clock = ScaledClock(SIM_SPEED) if args.sim else SYSTEM_CLOCK
    return machine, clock


class Report:
    def __init__(self, probe: str, args: argparse.Namespace):
        self.probe = probe
        self.out = Path(args.out)
        self.started = datetime.datetime.now(datetime.UTC)
        self.data: dict[str, Any] = {
            "probe": probe,
            "simulated": bool(args.sim),
            "started_utc": self.started.isoformat(timespec="seconds"),
            "multilbic_version": version("multilbic"),
            "provenance": _provenance(),
            "host": {
                "node": platform.node(),
                "platform": sys.platform,
                "machine": platform.machine(),
                "python": platform.python_version(),
            },
            "arguments": {
                k: v for k, v in vars(args).items() if _jsonable(v)
            },
            "results": {},
            "notes": [],
        }
        if args.sim:
            self.note(
                "SIMULATED: these numbers describe the simulator, "
                "not the machine."
            )

    def __setitem__(self, key: str, value: Any) -> None:
        self.data["results"][key] = value

    def __getitem__(self, key: str) -> Any:
        return self.data["results"][key]

    def note(self, text: str) -> None:
        self.data["notes"].append(text)
        say(f"  note: {text}")

    def save(self) -> Path:
        self.out.mkdir(parents=True, exist_ok=True)
        stamp = self.started.strftime("%Y%m%dT%H%M%SZ")
        tag = "sim" if self.data["simulated"] else "real"
        path = self.out / f"{stamp}_{self.probe}_{tag}.json"
        self.data["finished_utc"] = datetime.datetime.now(
            datetime.UTC
        ).isoformat(timespec="seconds")
        path.write_text(json.dumps(self.data, indent=2, default=str) + "\n")
        say(f"report: {path}")
        return path


def _provenance() -> dict[str, Any]:
    try:
        from smuniversal_lab_suite.core.provenance import head_commit

        sha, dirty, paths = head_commit(REPO_ROOT)
        return {"commit": sha, "dirty": dirty, "dirty_paths": paths[:20]}
    except Exception as exc:  # no git on the box: say so, don't fail
        return {"commit": None, "error": str(exc)}


def _jsonable(value: Any) -> bool:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return False
    return True
