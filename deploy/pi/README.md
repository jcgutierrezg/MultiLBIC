# Raspberry Pi deployment

Kept here so the Pi can be rebuilt if its microSD card fails.

The Pi is a Raspberry Pi 4 running **Ubuntu 24.04** (not Raspberry Pi
OS), with a monitor attached. It is reached over SSH as `multilbic`;
setting that up is in [`docs/bench.md`](../../docs/bench.md).

## Install

`setup.sh` does all of the steps below and is safe to re-run; the bench
runbook ([`docs/bench.md`](../../docs/bench.md)) shows how to fetch and
run it. By hand:

Ubuntu 24.04 ships Python 3.12, older than 3.14. Python 3.14 comes from
the deadsnakes PPA, whose `python3.14-tk` uses Ubuntu's Tk 8.6, built
with Xft: smooth text in the window (D21). uv can provide a 3.14 too,
and `setup.sh` falls back to it, but that one's Tk 9.0 was built
without Xft and draws jagged bitmap fonts (seen 2026-10-26).

0. Install git and curl, which Ubuntu does not always include, and
   Python 3.14 with Tk:
   ```bash
   sudo apt install git curl
   sudo add-apt-repository ppa:deadsnakes/ppa
   sudo apt install python3.14 python3.14-venv python3.14-tk
   ```
1. Install uv:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
2. Clone the repository:
   ```bash
   git clone https://github.com/jcgutierrezg/MultiLBIC.git
   ```
3. From inside the clone, install the dependencies on that Python:
   ```bash
   uv sync --python /usr/bin/python3.14
   ```
4. Check that Tk works on the Pi's display, and draws smooth text (the
   answer should be `xft`; `x11` means jagged):
   ```bash
   uv run python -c "import tkinter; r = tkinter.Tk(); print(r.tk.call('::tk::pkgconfig', 'get', 'fontsystem')); r.destroy()"
   ```
5. Run the tests:
   ```bash
   uv run pytest
   ```

## USB boot check

The laser Xiao sometimes fails to appear on USB after the Pi starts, and
used to need its cable replugged (what is known is in
[`docs/hardware.md`](../../docs/hardware.md#usb-at-boot)). A small root
service checks at every boot and, only if the Xiao is missing, switches
the Pi's USB power off and on, the same as a replug.

- `usb-check.sh`: the check, installed as `/usr/local/sbin/multilbic-usb-check`.
- `multilbic-usb-check.service`: runs it once at boot.
- `install-usb-check.sh`: installs or updates both.

Install, once (needs `uhubctl`):

```bash
sudo apt install uhubctl
```

```bash
sudo bash ~/MultiLBIC/deploy/pi/install-usb-check.sh
```

Test the power cycle now. Every USB device drops for a few seconds and
comes back:

```bash
sudo multilbic-usb-check --force
```

What it did at each boot (runs by hand only print to the terminal):

```bash
journalctl -t multilbic-usb-check
```

Verified 2026-10-20: installed and enabled; a forced cycle dropped every
USB device and the Xiao was back 7 s later. The real "missing at boot"
path has not been exercised yet, because the failure has not recurred.

## Serial devices

- `Serials.txt`: the USB serial numbers the old udev rules matched on.
  Line 2 is the SKR, line 3 the laser Xiao, line 1 the retired
  instrumentation Xiao. The current Ubuntu install has **no udev
  rules**, so there are no `/dev/SKR`-style names; the boards are listed
  in [`docs/hardware.md`](../../docs/hardware.md#topology).
- **Fixed names without udev rules:** Linux already makes
  `/dev/serial/by-id/usb-<vendor>_<model>_<serial>...` links from each
  board's USB serial number, and `machine.toml` uses those. A replaced
  board has a new serial, so its path in `machine.toml` changes with it
  (`python -m multilbic.bench.ports --real` shows the new one).
- The user running the app needs to be in the `dialout` group to open
  serial ports. Ubuntu does not add it by default; `setup.sh` does.
- **ModemManager** probes every new `/dev/ttyACM*` device (the SKR, the
  Xiao and the miniSMU all are), and **brltty** claims CH340/CH341
  USB-serial adapters. Both are covered in
  [`docs/bench.md`](../../docs/bench.md#before-the-first-session).
- **The miniSMU has its own power switch.** Switch it on before starting
  the software; switched off, it is simply absent from USB.

## Owed

- A desktop launcher (Phase 7).
