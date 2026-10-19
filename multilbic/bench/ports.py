"""
Which serial device is which.

    python -m multilbic.bench.ports

Lists every serial port with its USB identity, says which of the
MultiLBIC boards each looks like, and what the `/dev/...` symlinks from
the udev rules point at. Run it once on the Pi: it answers which serial
number in `deploy/pi/Serials.txt` belongs to which board, and on which
port the miniSMU (which has no udev name yet) sits.

No device is opened, so it is safe to run with anything connected. The
guesses come from USB identity alone:

* the miniSMU reports its serial (`LUNAR-TUVOK-7966`) and Undalogic's
  product id, as SMUniversal's address detection knows;
* the Seeeduino Xiao is a SAMD21 with Seeed's vendor id;
* the SKR 1.4 Turbo (LPC1769) enumerates as a generic CDC device;
* the TFT35 sits behind a USB-serial adapter (CH340, CP210x, FTDI...).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from multilbic.bench.report import Report, base_parser, say

SEEED_VID = 0x2886
USB_SERIAL_ADAPTER_VIDS = {
    0x1A86: "CH340",
    0x10C4: "CP210x",
    0x0403: "FTDI",
    0x067B: "PL2303",
}
SYMLINKS = ("/dev/SKR", "/dev/S_LASER", "/dev/TFT35", "/dev/S_INSTR")
SERIALS_FILE = Path(__file__).resolve().parents[2] / "deploy/pi/Serials.txt"


def guess(port) -> str:
    serial_number = (port.serial_number or "").upper()
    text = " ".join(
        str(x) for x in (port.description, port.manufacturer, port.product)
    ).lower()
    if "LUNAR-TUVOK" in serial_number or "minismu" in text:
        return "miniSMU"
    if port.vid == SEEED_VID or "xiao" in text or "seeed" in text:
        return "laser board (Xiao)"
    if port.vid in USB_SERIAL_ADAPTER_VIDS:
        return f"USB-serial adapter ({USB_SERIAL_ADAPTER_VIDS[port.vid]}): TFT35?"
    if "marlin" in text or "lpc" in text or "skr" in text:
        return "SKR (Marlin)"
    return "unknown"


def describe_ports(ports) -> list[dict]:
    known = []
    if SERIALS_FILE.exists():
        known = [s.strip().upper() for s in SERIALS_FILE.read_text().split()]
    rows = []
    for port in sorted(ports, key=lambda p: p.device):
        serial_number = port.serial_number or ""
        rows.append(
            {
                "device": port.device,
                "vid": f"{port.vid:04X}" if port.vid is not None else None,
                "pid": f"{port.pid:04X}" if port.pid is not None else None,
                "serial_number": serial_number,
                "in_serials_txt": serial_number.upper() in known,
                "manufacturer": port.manufacturer,
                "product": port.product,
                "description": port.description,
                "guess": guess(port),
            }
        )
    return rows


def symlinks() -> dict[str, str | None]:
    if not sys.platform.startswith("linux"):
        return {}
    return {
        link: os.path.realpath(link) if os.path.exists(link) else None
        for link in SYMLINKS
    }


def _sim_ports():
    from types import SimpleNamespace

    def port(device, vid, pid, serial, manufacturer, product):
        return SimpleNamespace(
            device=device, vid=vid, pid=pid, serial_number=serial,
            manufacturer=manufacturer, product=product,
            description=product,
        )

    return [
        port("/dev/ttyACM0", 0x1D50, 0x6029, "SIMSKR", "Marlin", "Marlin USB"),
        port("/dev/ttyACM1", SEEED_VID, 0x802F, "SIMXIAO", "Seeed", "XIAO"),
        port("/dev/ttyACM2", 0x2E8A, 0x000A, "LUNAR-TUVOK-7966", "Undalogic",
             "miniSMU"),
        port("/dev/ttyUSB0", 0x1A86, 0x7523, "", "QinHeng", "USB Serial"),
    ]


def main(argv: list[str] | None = None) -> int:
    args = base_parser("List serial ports and guess which board is which.")
    args = args.parse_args(argv)
    report = Report("ports", args)
    if args.sim:
        ports = _sim_ports()
    else:
        from serial.tools import list_ports

        ports = list_ports.comports()
    rows = describe_ports(ports)
    report["ports"] = rows
    report["symlinks"] = symlinks()
    for row in rows:
        say(
            f"{row['device']:<16} {row['vid'] or '----'}:{row['pid'] or '----'}"
            f"  serial {row['serial_number'] or '-':<34}"
            f"{'(in Serials.txt) ' if row['in_serials_txt'] else ''}"
            f"-> {row['guess']}"
        )
    for link, target in report["symlinks"].items():
        say(f"{link:<16} -> {target or 'missing'}")
    if not rows:
        report.note("no serial ports found")
    report.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
