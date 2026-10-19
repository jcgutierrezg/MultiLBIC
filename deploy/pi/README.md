# Raspberry Pi deployment

Kept here so the Pi can be rebuilt if its microSD card fails.

The Pi is a Raspberry Pi 4 running **Ubuntu 24.04** (not Raspberry Pi
OS), with a monitor attached.

**Not yet tried on the Pi.** These steps match what CI's ARM job does,
which is the closest stand-in available until SSH access is set up.

## Install

`setup.sh` does all of the steps below and is safe to re-run; the bench
runbook ([`docs/bench.md`](../../docs/bench.md)) shows how to fetch and
run it. By hand:

Ubuntu 24.04 ships Python 3.12, older than 3.14, so uv provides one.

0. Install git and curl, which Ubuntu does not always include:
   ```bash
   sudo apt install git curl
   ```
1. Install uv:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
2. Clone the repository:
   ```bash
   git clone https://github.com/jcgutierrezg/MultiLBIC.git
   ```
3. From inside the clone, install a uv-managed Python 3.14 and the
   dependencies:
   ```bash
   uv sync --managed-python
   ```
4. Check that Tk works on the Pi's display:
   ```bash
   uv run python -c "import tkinter; tkinter.Tk().destroy(); print('tk ok')"
   ```
5. Run the tests:
   ```bash
   uv run pytest
   ```

## Serial devices

- `Serials.txt`: the USB serial numbers the old udev rules matched on.
  Line 2 is the SKR. The other two look like the two Xiaos. The current
  Ubuntu install has **no udev rules**, so there are no `/dev/SKR`-style
  names; which boards are identified so far is in
  [`docs/hardware.md`](../../docs/hardware.md#topology).
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

## Owed

- SSH access for remote bench work: steps in [`docs/bench.md`](../../docs/bench.md).
- A desktop launcher (Phase 7).
