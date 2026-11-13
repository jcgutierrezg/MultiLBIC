"""Draws phase-margin.png: the same small disturbance on the channel with
three phase margins, to show what the number means.

A laser lit at 40 mA; at t = 0 one extra milliamp is pushed into the
sense resistor, so the loop has to take 1 mA off the laser. Four
channels: the loop parts first drawn (220 ohm, 1 kohm, 10 nF) with
none, 30 nF and 100 nF across the module (-6, 10 and 29 degrees), and
the parts now on the schematic (59 degrees or more on both loops).

    python plot_margins.py

Needs LTspice (see run_all.py) and matplotlib.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
from run_all import ltspice

matplotlib.use("Agg")

HERE = Path(__file__).parent
#: LTspice counts time from the start of what it saves (1.9 ms here);
#: the disturbance comes 0.1 ms after that.
T0 = 1e-4
FIRST = {"R103 oa gate 3.9k": "R103 oa gate 220",
         "R106 sfb fb 10k": "R106 sfb fb 1k",
         "C102 oa fb 1n": "C102 oa fb 10n"}
CASES = [
    ("first parts, no capacitance across the module: "
     "margin −6°, it oscillates for good", True, "0"),
    ("first parts, 30 nF across the module: "
     "margin 10°, it rings a dozen times", True, "30n"),
    ("first parts, 100 nF across the module: "
     "margin 29°, it rings twice", True, "100n"),
    ("parts now on the schematic, no capacitance: "
     "margin 59° at least, one small overshoot", False, "0"),
]
NETLIST = """* phase margin demonstration
.include models.lib
.include board.inc
.param ISET=40m LCAB=0.5u ACBRK=0 ACBRK2=0 C105V=0 RLID=0.1 VTS=0.75 VTC=1.3
.param CMOD={cmod}
V5 v5in 0 5
V3 v3 0 3.3
Ven en 0 3.3
Vdac dac 0 {{ISET*50}}
Lcab v5 lasp {{LCAB}} Rser=0.2
Cmod lasp drn {{CMOD+1f}}
Vlas lasp lasa 0
Xlas lasa drn opt LASER2
Idist 0 sns PULSE(0 1m 2m 100n 100n 1 2)
.save I(Vlas)
.tran 0 2.6m 1.9m 0.1u
.end
"""


def read_ascii_raw(path: Path) -> tuple[list[float], list[float]]:
    data = path.read_bytes()
    text = data.decode("utf-16-le" if data[1:2] == b"\x00" else "utf-8",
                       errors="replace")
    values = text.split("Values:")[1].split()
    time = [float(v) for v in values[1::3]]
    amps = [float(v) for v in values[2::3]]
    return time, amps


def run(first: bool, cmod: str) -> tuple[list[float], list[float]]:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "models.lib").write_text(
            (HERE / "models.lib").read_text(encoding="utf-8"),
            encoding="utf-8")
        board = (HERE / "board.inc").read_text(encoding="utf-8")
        if first:
            for now, then in FIRST.items():
                if now not in board:
                    raise SystemExit(f"board.inc no longer has: {now}")
                board = board.replace(now, then)
        (d / "board.inc").write_text(board, encoding="utf-8")
        (d / "m.cir").write_text(NETLIST.format(cmod=cmod), encoding="utf-8")
        subprocess.run([ltspice(), "-ascii", "-b", "m.cir"], cwd=d,  # noqa: S603
                       check=False, timeout=600)
        return read_ascii_raw(d / "m.raw")


def main() -> None:
    fig, axes = plt.subplots(len(CASES), 1, figsize=(8, 9.5), sharex=True)
    for ax, (title, first, cmod) in zip(axes, CASES, strict=True):
        t, i = run(first, cmod)
        ax.plot([(x - T0) * 1e6 for x in t], [y * 1e3 for y in i],
                color="#0b5cad", linewidth=1.1)
        ax.axhline(38.84, color="#888888", linewidth=0.8, linestyle="--")
        ax.set_title(title, fontsize=10, loc="left")
        ax.set_ylabel("laser current, mA")
        ax.set_xlim(-30, 330)
        ax.grid(True, alpha=0.3)
    axes[-1].set_xlabel("time after the disturbance, µs "
                        "(dashed: where the current should settle)")
    fig.suptitle("The same 1 mA disturbance, four phase margins",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(HERE / "phase-margin.png", dpi=130)


if __name__ == "__main__":
    main()
