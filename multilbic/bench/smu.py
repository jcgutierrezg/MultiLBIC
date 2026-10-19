"""
The miniSMU on the bench: what streaming really delivers.

    python -m multilbic.bench.smu --real --port /dev/ttyACM2 --load open
    python -m multilbic.bench.smu --real --port /dev/ttyACM2 --load dark-cell

`--load` says what is connected to channel 1 (`open`, `dark-cell`, or
anything else, e.g. `10Mohm`) and goes into the report. The output
sources 0 V with a 1 mA limit throughout, which is safe for anything
plausibly attached.

Stages:

1. **Identity**: firmware (1.5.0+ adds the current range to packets)
   and temperatures.
2. **Raw packets**: the first lines exactly as the instrument sends
   them, so the packet format is on record, not assumed.
3. **Rate sweep** (`--rates`, default 100,250,500,1000,2000 Hz, for
   `--seconds` each): achieved rate by the instrument's clock and by the
   host's count, timestamp resolution (smallest step) and jitter, gaps,
   parse errors.
4. **Two channels** at `--dual-rate`: whether both keep up together.
5. **Clocks** (`--clock-seconds`, default 60): a fit of the instrument's
   timestamps against the Pi's receipt times. The slope gives the
   drift between the two clocks in ppm. The spread above the fastest
   packets is the arrival latency, which Phase 3's clock mapping has to
   see through.
6. **Noise at 0 V** per current range (auto, then 1 µA, 25 µA and
   650 µA fixed), at `--noise-rate`: mean (the offset), standard
   deviation and peak-to-peak. With `--load dark-cell` this is the floor
   an LBIC signal has to clear.
"""

from __future__ import annotations

import sys

from multilbic.bench.report import (
    Report,
    base_parser,
    linear_fit,
    say,
    setup,
    summary,
)
from multilbic.hardware.smu import PhotocurrentSmu, StreamSample, open_smu

CURRENT_LIMIT_A = 1e-3
RAW_PACKETS = 20
NOISE_RANGES: tuple[tuple[str, int | None], ...] = (
    ("auto", None),
    ("1uA", 0),
    ("25uA", 1),
    ("650uA", 2),
)


def stream_for(smu: PhotocurrentSmu, clock, channels, rate, seconds):
    smu.stream.start(channels=channels, rate_hz=rate)
    clock.sleep(seconds)
    stats = smu.stream.stop()
    return stats, smu.stream.drain()


def step_stats(samples: list[StreamSample], channel: int, rate: float) -> dict:
    stamps = [s.device_ms for s in samples if s.channel == channel]
    steps = [b - a for a, b in zip(stamps, stamps[1:], strict=False)]
    nominal_ms = 1000.0 / rate
    positive = [d for d in steps if d > 0]
    host = [s.host_s for s in samples if s.channel == channel]
    host_span = host[-1] - host[0] if len(host) > 1 else 0.0
    return {
        "samples": len(stamps),
        "rate_by_device_hz": (
            (len(stamps) - 1) / ((stamps[-1] - stamps[0]) / 1000.0)
            if len(stamps) > 1 and stamps[-1] > stamps[0]
            else None
        ),
        "rate_by_host_hz": (len(host) - 1) / host_span if host_span else None,
        "step_ms": summary(steps),
        "smallest_step_ms": min(positive) if positive else None,
        "distinct_steps_ms": sorted({round(d, 4) for d in steps})[:20],
        "repeated_stamps": sum(1 for d in steps if d == 0),
        # A gap is a step at least two clock ticks (ms) late as well as
        # 1.5x nominal: stamps are whole milliseconds, so at 500 Hz a 3 ms
        # step is rounding, not a lost sample (bench, 2026-10-19).
        "gaps": sum(
            1 for d in steps if d > 1.5 * nominal_ms and d >= nominal_ms + 2
        ),
        "backwards": sum(1 for d in steps if d < 0),
    }


def raw_packets(smu: PhotocurrentSmu, report: Report, rate: float) -> None:
    client = smu.stream._client
    connection = getattr(client, "_connection", None)
    if connection is None:
        report.note("raw packets: not available in simulation")
        return
    client.set_sample_rate(1, rate)
    client.start_streaming(1)
    lines = []
    try:
        for _ in range(RAW_PACKETS):
            lines.append(connection.readline().decode("ascii", "replace"))
    finally:
        client.stop_streaming(1)
    report["raw_packets"] = lines
    fields = {len(line.strip().split(",")) for line in lines if line.strip()}
    report["raw_packet_field_counts"] = sorted(fields)
    say(f"raw packet: {lines[0].strip()!r}, fields per packet {sorted(fields)}")


def rate_sweep(smu, clock, report: Report, rates, seconds) -> None:
    rows = []
    for rate in rates:
        stats, samples = stream_for(smu, clock, (1,), rate, seconds)
        row = {
            "requested_hz": rate,
            "parse_errors": stats.parse_errors,
            "idle_reads": stats.idle_reads,
            **step_stats(samples, 1, rate),
        }
        rows.append(row)
        by_device = row["rate_by_device_hz"] or 0.0
        say(
            f"{rate:>6.0f} Hz: got {by_device:8.1f} Hz by device clock, "
            f"smallest step {row['smallest_step_ms']} ms, "
            f"jitter {row['step_ms'].get('stdev') or 0:.3f} ms, "
            f"gaps {row['gaps']}, errors {stats.parse_errors}"
        )
    report["rate_sweep"] = rows


def dual(smu, clock, report: Report, rate, seconds) -> None:
    stats, samples = stream_for(smu, clock, (1, 2), rate, seconds)
    report["dual_channel"] = {
        "requested_hz": rate,
        "parse_errors": stats.parse_errors,
        "channel_1": step_stats(samples, 1, rate),
        "channel_2": step_stats(samples, 2, rate),
    }
    say(
        f"two channels at {rate:.0f} Hz: "
        f"{report['dual_channel']['channel_1']['rate_by_device_hz'] or 0:.1f} / "
        f"{report['dual_channel']['channel_2']['rate_by_device_hz'] or 0:.1f} Hz"
    )


def clocks(smu, clock, report: Report, rate, seconds) -> None:
    stats, samples = stream_for(smu, clock, (1,), rate, seconds)
    if len(samples) < 10:
        report.note("clocks: too few samples to fit")
        return
    host_ms = [s.host_s * 1000.0 for s in samples]
    device_ms = [s.device_ms - samples[0].device_ms for s in samples]
    slope, intercept = linear_fit(device_ms, host_ms)
    residual = [h - (slope * d + intercept) for h, d in zip(host_ms, device_ms, strict=True)]
    floor = min(residual)
    latency = [r - floor for r in residual]
    report["clocks"] = {
        "seconds": seconds,
        "samples": len(samples),
        "drift_ppm": (slope - 1.0) * 1e6,
        "arrival_latency_above_fastest_ms": summary(latency),
        "parse_errors": stats.parse_errors,
    }
    lat = report["clocks"]["arrival_latency_above_fastest_ms"]
    say(
        f"clocks: drift {report['clocks']['drift_ppm']:+.1f} ppm, arrival "
        f"latency above the fastest packet: median {lat['median']:.2f} ms, "
        f"max {lat['max']:.2f} ms"
    )


def noise(smu, clock, report: Report, rate, seconds) -> None:
    client = smu.stream._client
    rows = []
    for name, index in NOISE_RANGES:
        if index is None:
            client.set_autorange(1, True)
        else:
            client.set_autorange(1, False)
            client.set_current_range(1, index)
        stats, samples = stream_for(smu, clock, (1,), rate, seconds)
        currents = [s.current_a for s in samples if s.channel == 1]
        row = {
            "range": name,
            "current_a": summary(currents),
            "peak_to_peak_a": (max(currents) - min(currents)) if currents else None,
            "parse_errors": stats.parse_errors,
        }
        rows.append(row)
        c = row["current_a"]
        say(
            f"noise {name:>5}: mean {c.get('mean', 0):+.3e} A, "
            f"stdev {c.get('stdev') or 0:.3e} A, p-p {row['peak_to_peak_a'] or 0:.3e} A"
        )
    client.set_autorange(1, True)
    report["noise_0V"] = rows


def _open(args, clock) -> PhotocurrentSmu:
    if args.sim:
        from multilbic.sim.fake_smu import FakeMiniSMU, FakeMiniSMUTransport

        fake = FakeMiniSMU(clock, signal=lambda ch, t: 0.0, noise_a=2e-10)
        return PhotocurrentSmu(FakeMiniSMUTransport(fake), clock, (1, 2))
    if not args.port:
        raise SystemExit("pass --port (python -m multilbic.bench.ports finds it)")
    return open_smu(args.port, clock, (1, 2))


def _floats(text: str) -> list[float]:
    return [float(v) for v in text.split(",") if v.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = base_parser(__doc__.strip().split("\n")[0])
    parser.add_argument("--port", default="", help="miniSMU serial port")
    parser.add_argument(
        "--load", default="", help="what is on channel 1: open, dark-cell..."
    )
    parser.add_argument("--rates", default="100,250,500,1000,2000")
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--dual-rate", type=float, default=500.0)
    parser.add_argument("--clock-seconds", type=float, default=60.0)
    parser.add_argument("--noise-rate", type=float, default=1000.0)
    parser.add_argument("--noise-seconds", type=float, default=3.0)
    args = parser.parse_args(argv)
    if args.real and not args.load:
        parser.error("--load is required with --real: say what is connected")

    _, clock = setup(args)
    report = Report("smu", args)
    report["load"] = args.load or "simulated"
    smu = _open(args, clock)
    try:
        report["identity"] = smu.identify()
        report["firmware"] = smu.firmware
        report["firmware_streams_range"] = smu.firmware_streams_range
        report["temperatures_c"] = smu.stream._client.get_temperatures()
        say(f"{report['identity']}")
        if not smu.firmware_streams_range:
            report.note("firmware below 1.5.0: packets carry no current range")
        smu.prepare(bias_v=0.0, current_limit_a=CURRENT_LIMIT_A)
        smu.output_on()
        raw_packets(smu, report, rate=100.0)
        rate_sweep(smu, clock, report, _floats(args.rates), args.seconds)
        dual(smu, clock, report, args.dual_rate, args.seconds)
        clocks(smu, clock, report, args.noise_rate / 2, args.clock_seconds)
        noise(smu, clock, report, args.noise_rate, args.noise_seconds)
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        say(f"FAILED: {report['error']}")
        raise
    finally:
        try:
            smu.output_off()
        except Exception as exc:
            report.note(f"output off failed: {exc}")
        report.save()
        smu.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
