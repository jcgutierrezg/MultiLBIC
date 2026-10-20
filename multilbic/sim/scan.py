"""
A headless scan of the synthetic sample, in simulation.

    uv run python -m multilbic.sim.scan

Builds the simulated machine with the agreed faults (5 ms reply
latency, 20 µm backlash, the SMU clock 100 ppm fast, bench-like noise),
puts the synthetic sample on the carriage, and runs one laser's map
through the same session a real run uses (`multilbic.run.session`),
from a perfect corner calibration: home, XY under the laser, baseline,
rows, run file, map from the file alone, PNG. It prints how far the
recovered edges are from the true ones.

Everything below the fakes is the real code.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from multilbic.bench.report import provenance
from multilbic.clock import Clock, ScaledClock
from multilbic.config import load
from multilbic.config.machine import MachineConfig
from multilbic.run.rows import ScanDevices
from multilbic.run.session import RunRequest, Session
from multilbic.scan.mapping import MapResult, build_map
from multilbic.sim.rig import Faults, SimRig
from multilbic.sim.sample import SyntheticSample
from multilbic.store.image import save_png
from multilbic.store.runfile import read_run

#: Simulated seconds per real second. The scan's timing is checked to
#: fractions of a millisecond, so the clock sleeps precisely (see
#: `ScaledClock`), and a modest factor keeps thread scheduling from
#: adding latency the faults didn't ask for.
DEFAULT_SPEEDUP = 5.0
#: Where the sample's corner sits on the carriage: off-centre, so XY has
#: to move to place it.
CORNER_CARRIAGE_MM = (15.0, 16.0)


@dataclass
class SimScan:
    run_path: Path
    result: MapResult
    sample: SyntheticSample
    rig: SimRig
    laser: int


def simulate_scan(
    out_dir: str | Path,
    *,
    width_mm: float = 1.0,
    height_mm: float = 0.3,
    pixel_mm: float = 0.005,
    pitch_mm: float = 0.05,
    speed_mm_s: float = 1.0,
    laser: int = 3,
    serpentine: bool = True,
    faults: Faults | None = None,
    clock: Clock | None = None,
    machine: MachineConfig | None = None,
    baseline_s: float = 2.0,
    say=lambda text: None,
) -> SimScan:
    faults = faults or Faults()
    machine = sim_machine(machine or load(), faults)
    clock = clock or ScaledClock(DEFAULT_SPEEDUP, precise=True)
    sample = SyntheticSample.default(width_mm, height_mm)
    rig = SimRig(machine, clock, sample, CORNER_CARRIAGE_MM, faults)
    request = RunRequest(
        rig.perfect_calibration("synthetic"), (laser,),
        pixel_mm, pitch_mm, speed_mm_s, serpentine,
        baseline_s=baseline_s, allow_unmeasured=True,
    )
    rig.open()
    try:
        session = Session(
            ScanDevices(rig.marlin, rig.laser, rig.smu), machine, clock,
            request, out_dir, simulated=True, provenance=provenance(),
            say=say,
        )
        outcome = session.run()
    finally:
        rig.close()
    if outcome.status != "complete":
        raise RuntimeError(f"simulated run {outcome.status}")
    run_path = outcome.lasers[0].path
    result = build_map(read_run(run_path).scan_data())
    return SimScan(run_path, result, sample, rig, laser)


def sim_machine(machine: MachineConfig, faults: Faults) -> MachineConfig:
    """machine.toml as it will be once the bench has measured things:
    the A/B backlash known, the axis directions checked."""
    geometry = replace(
        machine.geometry,
        ab_backlash_mm=faults.backlash_mm,
        directions_measured=True,
    )
    return replace(machine, geometry=geometry)


@dataclass(frozen=True)
class PositionErrors:
    """Mapped minus true A position of every sample, in mm, before and
    after the serpentine alignment, and the shift actually present."""

    direction: np.ndarray
    before: np.ndarray
    after: np.ndarray

    @property
    def true_shift_mm(self) -> float:
        """Forward-row error minus reverse-row error: the shift the
        alignment should have measured."""
        forward = self.before[self.direction > 0]
        reverse = self.before[self.direction < 0]
        return float(np.median(forward) - np.median(reverse))


def position_errors(scan: SimScan) -> PositionErrors:
    """Check each sample's mapped position against where the simulated
    stage really was when the sample was taken. Only a simulation can
    do this: it knows the true time of every stamp and the stage's
    whole path, backlash included.

    Only samples on the sample are counted. The run-up is where the
    backlash is taken up after a reversal, so positions there are off by
    up to the whole backlash; that is what the run-up is for."""
    rig, result = scan.rig, scan.result
    found = result.alignment.found
    shift = result.alignment.shift_mm if found else 0.0
    added = rig.faults.backlash_mm / 2 if found else 0.0
    directions, before, after = [], [], []
    for row in result.rows:
        for u, stamp in zip(row.u_mm, row.device_ms, strict=True):
            t = rig.fake_smu.true_time(float(stamp))
            true_u = rig.true_uv(t, scan.laser)[0]
            if not 0.0 <= true_u <= scan.sample.width_mm:
                continue
            error = float(u) - true_u
            directions.append(row.direction)
            after.append(error)
            before.append(error + row.direction * shift / 2 - added)
    return PositionErrors(
        np.array(directions), np.array(before), np.array(after)
    )


def edge_errors(scan: SimScan) -> dict[str, list[float]]:
    """Recovered minus true position of each A edge, per row, in mm.

    Each edge is found in the binned map as the point halfway between
    the levels on either side of it, interpolated between pixels. Only
    rows well inside the cells' B range are used, so the levels are
    flat."""
    grid = scan.result.grid
    sample = scan.sample
    nm_level = scan.rig.machine.laser(
        int(read_run(scan.run_path).header["laser"])
    ).wavelength_nm
    u = grid.u_centres
    errors: dict[str, list[float]] = {}
    spot = sample.spot_sigma_mm
    edges = sample.u_edges()
    for edge in edges:
        nearest = min(
            (abs(e - edge) for e in edges if e != edge), default=1.0
        )
        reach = min(4 * spot + 0.005, nearest / 2)
        lo_u, hi_u = edge - reach, edge + reach
        found = []
        for k, v in enumerate(grid.v_centres):
            if not _row_is_flat(sample, v):
                continue
            left = sample.current(nm_level, lo_u, v)
            right = sample.current(nm_level, hi_u, v)
            if abs(right - left) < 0.2 * abs(_peak(sample, nm_level)):
                continue
            half = (left + right) / 2
            row = grid.values[k]
            window = (u >= lo_u) & (u <= hi_u) & np.isfinite(row)
            crossing = _crossing(u[window], row[window], half)
            if crossing is not None:
                found.append(crossing - edge)
        if found:
            errors[f"u={edge:.4f}"] = found
    return errors


def v_edge_errors(scan: SimScan) -> dict[str, list[float]]:
    """Recovered minus true position of each B edge, per pixel column,
    in mm. Rows are a pitch apart, so this is only as fine as the pitch:
    the crossing is interpolated between row centres. Only columns well
    away from every A edge are used."""
    grid = scan.result.grid
    sample = scan.sample
    nm = scan.rig.machine.laser(
        int(read_run(scan.run_path).header["laser"])
    ).wavelength_nm
    v = grid.v_centres
    keep_off = 4 * sample.spot_sigma_mm + grid.pixel_mm
    columns = [
        j for j, u in enumerate(grid.u_centres)
        if all(abs(u - e) > keep_off for e in sample.u_edges())
    ]
    errors: dict[str, list[float]] = {}
    peak = _peak(sample, nm)
    for edge in sample.v_edges():
        lo_v, hi_v = edge - grid.pitch_mm, edge + grid.pitch_mm
        found = []
        for j in columns:
            u = grid.u_centres[j]
            below = sample.current(nm, u, edge - 4 * sample.spot_sigma_mm)
            above = sample.current(nm, u, edge + 4 * sample.spot_sigma_mm)
            if abs(above - below) < 0.2 * peak:
                continue
            column = grid.values[:, j]
            window = (v >= lo_v) & (v <= hi_v) & np.isfinite(column)
            crossing = _crossing(v[window], column[window], (below + above) / 2)
            if crossing is not None:
                found.append(crossing - edge)
        if found:
            errors[f"v={edge:.4f}"] = found
    return errors


def _peak(sample: SyntheticSample, nm: float) -> float:
    return max(abs(p.amps_at(nm)) for p in sample.patches)


def _row_is_flat(sample: SyntheticSample, v: float) -> bool:
    margin = 4 * sample.spot_sigma_mm
    return all(
        abs(v - e) > margin for e in sample.v_edges()
    )


def _crossing(u: np.ndarray, y: np.ndarray, level: float) -> float | None:
    above = y > level
    flips = np.nonzero(above[1:] != above[:-1])[0]
    if flips.size != 1:
        return None
    i = int(flips[0])
    y0, y1 = y[i], y[i + 1]
    return float(u[i] + (level - y0) / (y1 - y0) * (u[i + 1] - u[i]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default="runs", help="folder for the files")
    parser.add_argument("--width", type=float, default=1.0, help="mm")
    parser.add_argument("--height", type=float, default=0.3, help="mm")
    parser.add_argument("--pixel", type=float, default=0.005, help="mm")
    parser.add_argument("--pitch", type=float, default=0.05, help="mm")
    parser.add_argument("--speed", type=float, default=1.0, help="mm/s")
    parser.add_argument("--laser", type=int, default=3)
    parser.add_argument("--one-direction", action="store_true")
    parser.add_argument("--no-faults", action="store_true")
    parser.add_argument(
        "--speedup", type=float, default=DEFAULT_SPEEDUP,
        help="simulated seconds per real second",
    )
    args = parser.parse_args(argv)
    scan = simulate_scan(
        args.out,
        width_mm=args.width, height_mm=args.height,
        pixel_mm=args.pixel, pitch_mm=args.pitch,
        speed_mm_s=args.speed, laser=args.laser,
        serpentine=not args.one_direction,
        faults=Faults.none() if args.no_faults else Faults(),
        clock=ScaledClock(args.speedup, precise=True),
        say=lambda text: print(text, flush=True),
    )
    png = save_png(
        scan.result, scan.run_path.with_suffix(".png"),
        title=f"simulated, laser {args.laser}",
    )
    r = scan.result
    print(f"run file: {scan.run_path}")
    print(f"map: {png}")
    print(f"clock map: {r.clock.as_dict()}")
    print(f"alignment: {r.alignment.as_dict()}")
    print(f"baseline: {r.baseline.as_dict()}")
    p = position_errors(scan)
    print(
        f"true serpentine shift {p.true_shift_mm * 1000:+.2f} µm; "
        f"sample positions after alignment: worst "
        f"{np.abs(p.after).max() * 1000:.2f} µm over {p.after.size}"
    )
    for edges in (edge_errors(scan), v_edge_errors(scan)):
        for edge, errors in edges.items():
            um = np.array(errors) * 1000
            print(
                f"edge {edge}: error {np.median(um):+.1f} µm median, "
                f"{np.abs(um).max():.1f} µm worst over {um.size}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
