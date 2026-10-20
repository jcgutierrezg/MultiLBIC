"""
Marlin on the bench: what it is really running, and how it really times.

    python -m multilbic.bench.marlin --real                      # no motion
    python -m multilbic.bench.marlin --real --home --motion      # + AB moves
    python -m multilbic.bench.marlin --real --home --motion --speeds 3,4,5

Stages, each opted into:

1. **Always, nothing moves.** Identity, the settings actually running
   (`M503`: EEPROM can differ from the compiled defaults), TMC driver
   status (`M122`), and the round-trip time of a command (`M114` x 100).
2. **`--home`.** Times `G28`. Sensorless: each axis drives into its stop.
3. **`--motion`** (needs `--home`). Only A and B move, between 10 and
   20 mm, around the middle of their range:
   * **move timing.** Moves of 1-10 mm at 1 and 2 mm/s, each timed from
     sending `G1` to `M400` returning. A straight-line fit of time
     against distance gives the real speed (slope) and the fixed
     overhead (intercept): first-move delay, acceleration and serial
     latency together. Also compared against the simulator's model.
   * **stop.** A 10 s move is stopped with `M410` after 2 s; where it
     stopped says how quickly Stop acts.
   * **keepalive.** Spacing of `busy: processing` during a long `M400`.
4. **`--speeds 3,4,5`** (needs `--motion`). Raises the A/B max feedrate
   with `M203`, **for this power cycle only** (nothing is saved to
   EEPROM; the original value is restored at the end), and runs 20 mm
   back-and-forth moves at each speed. Watch and listen: lost steps
   don't show in the numbers, because there is no encoder. `M122` after
   each speed records driver flags.
"""

from __future__ import annotations

import dataclasses
import re
import sys

from multilbic.bench.report import (
    Report,
    base_parser,
    linear_fit,
    say,
    setup,
    summary,
)
from multilbic.config.machine import MachineConfig
from multilbic.hardware.link import SerialLink
from multilbic.hardware.marlin import Marlin
from multilbic.sim import motion
from multilbic.sim.motion import AxisLimits

ROUND_TRIPS = 100
TIMING_DISTANCES_MM = (1.0, 2.0, 5.0, 10.0)
TIMING_FEEDS_MM_S = (1.0, 2.0)
BASE_A_MM = 10.0
BASE_B_MM = 10.0
STOP_AFTER_S = 2.0
LONG_MOVE_MM = 20.0
DEFAULT_ACCEL_MM_S2 = 100.0


def model_duration(machine: MachineConfig, distance: float, feed: float) -> float:
    """What the simulator's model predicts for a single-axis A move."""
    limits = {
        "A": AxisLimits(machine.ab.max_feed_mm_s, machine.ab.max_accel_mm_s2)
    }
    block = motion.plan(
        {"A": 0.0}, {"A": distance}, feed, limits, DEFAULT_ACCEL_MM_S2, 0.0
    )
    return block.duration


def identify(marlin: Marlin, report: Report) -> None:
    info = marlin.open()
    report["identity"] = {
        "firmware": info.firmware_name,
        "machine_type": info.machine_type,
        "fields": info.fields,
        "capabilities": info.capabilities,
        "advanced_ok": marlin.advanced_ok,
    }
    say(f"firmware {info.firmware_name}, machine {info.machine_type}")
    settings = marlin.settings()
    report["m503"] = settings
    for line in settings:
        if re.search(r"M(92|201|203|204|425|914)\b", line):
            say(f"  {line.removeprefix('echo:').strip()}")
    report["m122"] = list(marlin.send("M122", timeout=10.0).lines)
    report["start_position"] = marlin.position()


def round_trips(marlin: Marlin, clock, report: Report) -> None:
    times = []
    for _ in range(ROUND_TRIPS):
        start = clock.now()
        marlin.send("M114")
        times.append((clock.now() - start) * 1000.0)
    report["m114_round_trip_ms"] = summary(times)
    say(
        f"M114 round trip: median {report['m114_round_trip_ms']['median']:.2f} ms, "
        f"max {report['m114_round_trip_ms']['max']:.2f} ms"
    )


def home(marlin: Marlin, clock, report: Report) -> None:
    say("homing (sensorless: each axis drives into its stop)...")
    start = clock.now()
    marlin.home()
    report["home_s"] = clock.now() - start
    report["homed_position"] = marlin.position()
    say(f"homed in {report['home_s']:.1f} s")


def timed_move(marlin: Marlin, clock, feed: float, **target) -> float:
    start = clock.now()
    marlin.move_to(feed_mm_s=feed, **target)
    marlin.wait_idle(timeout=10.0)
    return clock.now() - start


def move_timing(marlin, machine, clock, report: Report) -> None:
    marlin.move_to(a=BASE_A_MM, b=BASE_B_MM, feed_mm_s=1.0)
    marlin.wait_idle(timeout=30.0)
    results = {}
    for axis in ("a", "b"):
        base = BASE_A_MM if axis == "a" else BASE_B_MM
        for feed in TIMING_FEEDS_MM_S:
            rows = []
            for distance in TIMING_DISTANCES_MM:
                out = timed_move(marlin, clock, feed, **{axis: base + distance})
                back = timed_move(marlin, clock, feed, **{axis: base})
                predicted = model_duration(machine, distance, feed)
                rows.append(
                    {
                        "distance_mm": distance,
                        "out_s": out,
                        "back_s": back,
                        "model_s": predicted,
                    }
                )
            xs = [r["distance_mm"] for r in rows for _ in (0, 1)]
            ys = [t for r in rows for t in (r["out_s"], r["back_s"])]
            slope, intercept = linear_fit(xs, ys)
            key = f"{axis.upper()}@{feed:g}mm/s"
            results[key] = {
                "moves": rows,
                "fitted_speed_mm_s": 1.0 / slope,
                "fixed_overhead_s": intercept,
                "mean_excess_over_model_s": sum(
                    t - r["model_s"]
                    for r in rows
                    for t in (r["out_s"], r["back_s"])
                )
                / (2 * len(rows)),
            }
            say(
                f"{key}: real speed {1.0 / slope:.3f} mm/s, fixed overhead "
                f"{intercept * 1000:.0f} ms, "
                f"{results[key]['mean_excess_over_model_s'] * 1000:.0f} ms "
                f"slower than the model on average"
            )
    report["move_timing"] = results


#: Fixed, so stop results stay comparable whatever the A/B ceiling is.
STOP_FEED_MM_S = 2.0


def stop_test(marlin: Marlin, machine, clock, report: Report) -> None:
    feed = STOP_FEED_MM_S
    marlin.move_to(a=BASE_A_MM, feed_mm_s=feed)
    marlin.wait_idle(timeout=30.0)
    sent = clock.now()
    marlin.move_to(a=BASE_A_MM + LONG_MOVE_MM, feed_mm_s=feed)
    clock.sleep(STOP_AFTER_S)
    stop_at = clock.now()
    marlin.quickstop()
    marlin.wait_idle(timeout=10.0)
    idle_at = clock.now()
    stopped = marlin.position()["A"]
    travelled = stopped - BASE_A_MM
    # If motion started on send and stopped on M410, it would have gone
    # feed * (stop_at - sent). The shortfall is start delay + stop lag.
    ideal = feed * (stop_at - sent)
    report["stop"] = {
        "feed_mm_s": feed,
        "stop_sent_after_s": stop_at - sent,
        "travelled_mm": travelled,
        "travel_if_instant_mm": ideal,
        "shortfall_mm": ideal - travelled,
        "shortfall_s_at_feed": (ideal - travelled) / feed,
        "idle_after_stop_s": idle_at - stop_at,
    }
    say(
        f"stop: travelled {travelled:.3f} mm in {stop_at - sent:.2f} s "
        f"(shortfall {(ideal - travelled) / feed * 1000:.0f} ms at feed), "
        f"idle {(idle_at - stop_at) * 1000:.0f} ms after M410"
    )
    # Back to a known place for whatever comes next.
    marlin.move_to(a=BASE_A_MM, feed_mm_s=feed)
    marlin.wait_idle(timeout=30.0)


def keepalive(marlin: Marlin, machine, clock, report: Report) -> None:
    feed = 1.0
    marlin.move_to(a=BASE_A_MM + LONG_MOVE_MM / 2, feed_mm_s=feed)  # ~10 s
    # A time mark, not an index: the traffic log is a capped deque.
    mark = clock.now()
    marlin.wait_idle(timeout=5.0)
    busy = [
        t for t, direction, line in list(marlin.traffic)
        if t >= mark and direction == "<" and "busy" in line
    ]
    gaps = [b - a for a, b in zip(busy, busy[1:], strict=False)]
    report["keepalive"] = {"count": len(busy), "interval_s": summary(gaps)}
    say(f"keepalive: {len(busy)} busy lines, interval {summary(gaps).get('median')}")
    marlin.move_to(a=BASE_A_MM, feed_mm_s=machine.ab.max_feed_mm_s)
    marlin.wait_idle(timeout=30.0)


def _m203_ab(settings: list[str]) -> tuple[float, float] | None:
    for line in settings:
        if "M203" in line:
            a = re.search(r"\bA(\d+(?:\.\d+)?)", line)
            b = re.search(r"\bB(\d+(?:\.\d+)?)", line)
            if a and b:
                return float(a.group(1)), float(b.group(1))
    return None


def speeds(marlin: Marlin, machine, clock, report: Report, values) -> None:
    original = _m203_ab(report["m503"])
    if original is None:
        report.note("could not read M203 for A/B: speed test skipped")
        return
    rows = []
    try:
        for speed in values:
            marlin.send(f"M203 A{speed:g} B{speed:g}")
            raised = dataclasses.replace(
                machine,
                ab=dataclasses.replace(machine.ab, max_feed_mm_s=speed),
            )
            marlin.use_limits(raised)
            say(f"speed {speed:g} mm/s: 3 x {LONG_MOVE_MM:g} mm back and forth")
            times = []
            for _ in range(3):
                times.append(
                    timed_move(marlin, clock, speed, a=BASE_A_MM + LONG_MOVE_MM)
                )
                times.append(timed_move(marlin, clock, speed, a=BASE_A_MM))
            predicted = model_duration(raised, LONG_MOVE_MM, speed)
            m122 = list(marlin.send("M122", timeout=10.0).lines)
            rows.append(
                {
                    "speed_mm_s": speed,
                    "move_s": summary(times),
                    "model_s": predicted,
                    "m122": m122,
                }
            )
            say(
                f"  mean {summary(times)['mean']:.2f} s per move, "
                f"model {predicted:.2f} s"
            )
    finally:
        marlin.send(f"M203 A{original[0]:g} B{original[1]:g}")
        marlin.use_limits(machine)
        report.note(f"M203 A/B restored to {original}")
    report["speeds"] = rows
    report.note(
        "speeds: lost steps are invisible to these numbers; record what "
        "you saw and heard at each speed"
    )


def _open(args, machine, clock) -> Marlin:
    if args.sim:
        from multilbic.sim.fake_marlin import FakeMarlin
        from multilbic.sim.link import connect

        return Marlin(connect(FakeMarlin(machine), clock), machine, clock)
    port = args.port or machine.ports().skr
    if not port:
        raise SystemExit("no SKR port: pass --port or set it in machine.toml")
    return Marlin(SerialLink.open(port, machine.baud, clock), machine, clock)


def main(argv: list[str] | None = None) -> int:
    parser = base_parser(__doc__.strip().split("\n")[0])
    parser.add_argument("--port", default="", help="SKR serial port")
    parser.add_argument("--home", action="store_true")
    parser.add_argument("--motion", action="store_true")
    parser.add_argument(
        "--speeds", default="", help="comma-separated A/B speeds, mm/s"
    )
    args = parser.parse_args(argv)
    if args.motion and not args.home:
        parser.error("--motion needs --home")
    if args.speeds and not args.motion:
        parser.error("--speeds needs --motion")
    speed_values = [float(v) for v in args.speeds.split(",") if v.strip()]

    machine, clock = setup(args)
    report = Report("marlin", args)
    marlin = _open(args, machine, clock)
    try:
        identify(marlin, report)
        round_trips(marlin, clock, report)
        if args.home:
            home(marlin, clock, report)
        if args.motion:
            move_timing(marlin, machine, clock, report)
            stop_test(marlin, machine, clock, report)
            keepalive(marlin, machine, clock, report)
        if speed_values:
            speeds(marlin, machine, clock, report, speed_values)
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        say(f"FAILED: {report['error']}")
        if not args.sim:
            # Leave the stage still rather than mid-move.
            try:
                marlin.quickstop()
            except Exception as stop_exc:
                report.note(f"quickstop after failure also failed: {stop_exc}")
        raise
    finally:
        report["traffic_tail"] = [
            f"{t:.3f} {d} {line}" for t, d, line in list(marlin.traffic)[-200:]
        ]
        report.save()
        marlin.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
