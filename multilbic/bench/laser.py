"""
The laser board on the bench: firmware, and how long switching takes.

    python -m multilbic.bench.laser --real              # nothing lit
    python -m multilbic.bench.laser --real --lasers     # lights each laser

Always: identity and servo angles (checked against `machine.toml`), the
settle time, and the round-trip time of `STATE?` x 50.

With `--lasers`: selects every laser in an order that includes a
same-angle switch (1 -> 4, both 150°), timing each switch. A same-angle
switch should take one round trip, and the others about the settle time.
Then it repeats a few switches at shorter settle times, so you can watch
whether the servo has really stopped turning before the laser comes on.
That part is by eye: the board has no way to see the servo. Everything
ends with all lasers off and the original settle time restored.
"""

from __future__ import annotations

import sys

from multilbic.bench.report import Report, base_parser, say, setup, summary
from multilbic.hardware.laser import LaserBoard
from multilbic.hardware.link import SerialLink

ROUND_TRIPS = 50
#: Visits every laser, with 1 -> 4 as the same-angle switch.
SEQUENCE = (2, 1, 4, 3, 6, 5, 2)
TRIAL_SETTLES_MS = (1000, 500)


def _open(args, machine, clock) -> LaserBoard:
    if args.sim:
        from multilbic.sim.fake_laser import FakeLaserBoard
        from multilbic.sim.link import connect

        return LaserBoard(connect(FakeLaserBoard(), clock), machine, clock)
    port = args.port or machine.ports().laser
    if not port:
        raise SystemExit("no laser port: pass --port or set it in machine.toml")
    return LaserBoard(SerialLink.open(port, machine.baud, clock), machine, clock)


def timed_select(board: LaserBoard, clock, laser: int) -> float:
    start = clock.now()
    board.select(laser)
    return clock.now() - start


def main(argv: list[str] | None = None) -> int:
    parser = base_parser(__doc__.strip().split("\n")[0])
    parser.add_argument("--port", default="", help="laser board serial port")
    parser.add_argument("--lasers", action="store_true", help="light lasers")
    args = parser.parse_args(argv)
    machine, clock = setup(args)
    report = Report("laser", args)
    board = _open(args, machine, clock)
    original_settle = None
    try:
        report["firmware"] = board.open()
        original_settle = board.settle_ms
        report["settle_ms"] = original_settle
        report["state_at_start"] = vars(board.state())
        say(f"firmware {report['firmware']}, settle {original_settle} ms")

        times = []
        for _ in range(ROUND_TRIPS):
            start = clock.now()
            board.state()
            times.append((clock.now() - start) * 1000.0)
        report["state_round_trip_ms"] = summary(times)
        say(
            f"STATE? round trip: median "
            f"{report['state_round_trip_ms']['median']:.2f} ms"
        )

        if args.lasers:
            switches = []
            previous = board.state().laser
            for laser in SEQUENCE:
                # The board's own angle: after power-up the servo sits at
                # 90° with no laser lit, so "previous laser" can't say.
                angle_from = board.state().servo_angle_deg
                elapsed = timed_select(board, clock, laser)
                angle_to = machine.laser(laser).servo_angle_deg
                switches.append(
                    {
                        "from": previous,
                        "to": laser,
                        "servo_moved": angle_from != angle_to,
                        "seconds": elapsed,
                    }
                )
                say(
                    f"  {previous} -> {laser}: {elapsed * 1000:.0f} ms"
                    f"{'' if angle_from != angle_to else ' (same angle)'}"
                )
                previous = laser
            report["switches"] = switches

            trials = []
            for settle in TRIAL_SETTLES_MS:
                board.set_settle(settle)
                say(f"settle {settle} ms: watch 1 -> 2 -> 3")
                for laser in (1, 2, 3):
                    trials.append(
                        {
                            "settle_ms": settle,
                            "to": laser,
                            "seconds": timed_select(board, clock, laser),
                        }
                    )
            report["settle_trials"] = trials
            report.note(
                "settle trials: whether the servo had stopped before the "
                "laser lit is by eye; record what you saw at each setting"
            )
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        say(f"FAILED: {report['error']}")
        raise
    finally:
        try:
            board.resync()
            board.off()
            if original_settle is not None:
                board.set_settle(original_settle)
            report["state_at_end"] = vars(board.state())
        except Exception as exc:
            report.note(f"could not turn lasers off at the end: {exc}")
        report.save()
        board.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
