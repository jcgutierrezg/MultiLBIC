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

echo "== installing Python and dependencies"
# Ubuntu 24.04 ships Python 3.12, older than 3.14, so uv provides one.
uv sync --managed-python

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
uv run python -c "import sys, tkinter; print('python', sys.version.split()[0], '| Tk', tkinter.TkVersion)"

echo "== tests (hardware tests skipped)"
uv run pytest -q

echo "== done: $(git log -1 --format='%h %s')"
