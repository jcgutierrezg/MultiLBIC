#!/usr/bin/env bash
# Set up, or update, MultiLBIC on the Raspberry Pi. Safe to run again.
#
#   bash setup.sh [branch]          (default: main)
#
# Installs uv if missing, clones or updates ~/MultiLBIC on the branch,
# installs Python 3.14 and the dependencies through uv, checks that the
# user can open serial ports and that Tk imports, and runs the tests
# (the hardware ones stay skipped; see docs/bench.md for those).
#
# The checkout is a deployment copy: it is reset to match GitHub, so
# don't commit on the Pi.
set -euo pipefail

BRANCH="${1:-main}"
REPO_URL="https://github.com/jcgutierrezg/MultiLBIC.git"
DIR="${MULTILBIC_DIR:-$HOME/MultiLBIC}"

for tool in git curl; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "$tool is missing: sudo apt install git curl" >&2
        exit 1
    fi
done

if ! command -v uv >/dev/null 2>&1; then
    echo "== installing uv"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

if [ ! -d "$DIR/.git" ]; then
    echo "== cloning into $DIR"
    git clone "$REPO_URL" "$DIR"
fi
cd "$DIR"

echo "== checking out $BRANCH"
git fetch --prune origin
git checkout -B "$BRANCH" "origin/$BRANCH"

# The checkout may have replaced this very script. Bash goes on reading
# the old file it opened, so the rest of an update would run the old
# steps (seen 2026-10-21). Start again from the checked-out copy, once.
if [ -z "${MULTILBIC_SETUP_RESTARTED:-}" ]; then
    export MULTILBIC_SETUP_RESTARTED=1
    exec bash "$DIR/deploy/pi/setup.sh" "$BRANCH"
fi

echo "== installing Python and dependencies"
# Ubuntu 24.04 ships Python 3.12, older than 3.14. Deadsnakes' python3.14
# with python3.14-tk is preferred: its Tk is Ubuntu's 8.6, built with
# Xft, so the window's text is smooth. uv's own 3.14 works too, but its
# Tk was built without Xft and draws jagged bitmap fonts (D21,
# deploy/pi/README.md).
SYSTEM_PY=/usr/bin/python3.14
if [ -x "$SYSTEM_PY" ] && "$SYSTEM_PY" -c "import tkinter" 2>/dev/null; then
    # A .venv made from another interpreter is made again from this one.
    if [ -f .venv/pyvenv.cfg ] && ! grep -q "^home = /usr/bin" .venv/pyvenv.cfg; then
        echo "   .venv was made from another Python: making it again"
        rm -rf .venv
    fi
    uv sync --python "$SYSTEM_PY"
else
    echo "!! no $SYSTEM_PY with tkinter: using uv's Python 3.14, whose Tk"
    echo "   draws jagged text. For smooth text:"
    echo "   sudo add-apt-repository ppa:deadsnakes/ppa"
    echo "   sudo apt install python3.14 python3.14-venv python3.14-tk"
    echo "   then run this script again."
    uv sync --managed-python
fi

if ! id -nG "$USER" | grep -qw dialout; then
    echo "== adding $USER to dialout so serial ports can be opened"
    echo "   (log out and back in afterwards)"
    sudo usermod -aG dialout "$USER"
fi

# Ubuntu services that interfere with USB serial devices. Reported, not
# changed: whether to turn them off is the machine owner's call.
if systemctl is-active --quiet ModemManager 2>/dev/null; then
    echo "!! ModemManager is running: it probes /dev/ttyACM* devices (SKR,"
    echo "   laser Xiao, miniSMU). Turn it off with:"
    echo "   sudo systemctl disable --now ModemManager"
fi
if dpkg -s brltty >/dev/null 2>&1; then
    echo "!! brltty is installed: it claims CH340/CH341 USB-serial adapters"
    echo "   (possibly the TFT35's). If nothing uses a braille display:"
    echo "   sudo apt remove brltty"
fi

echo "== interpreter and Tk"
uv run --no-sync python -c "import sys, tkinter; print('python', sys.version.split()[0], sys.base_prefix, '| Tk', tkinter.TkVersion)"
# Smooth text needs a Tk linked with Xft; this asks the linker, so it
# works over SSH with no display.
TKMOD=$(uv run --no-sync python -c "import _tkinter; print(_tkinter.__file__)")
if ldd "$TKMOD" | grep -q libXft; then
    echo "   fonts: smooth (Tk uses Xft)"
else
    echo "!! fonts: jagged (this Tk has no Xft); see above"
fi

echo "== tests (hardware and simulator-timing tests skipped)"
# sim_timing: the simulator's millisecond timing needs a faster host
# than the Pi; CI runs those (pyproject.toml markers).
uv run --no-sync pytest -q -m "not sim_timing"

echo "== done: $(git log -1 --format='%h %s')"
