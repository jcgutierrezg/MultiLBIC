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
# Raspberry Pi OS ships an older Python than 3.14, so uv provides one.
uv sync --managed-python

if ! id -nG "$USER" | grep -qw dialout; then
    echo "== adding $USER to dialout so serial ports can be opened"
    echo "   (log out and back in afterwards)"
    sudo usermod -aG dialout "$USER"
fi

echo "== interpreter and Tk"
uv run python -c "import sys, tkinter; print('python', sys.version.split()[0], '| Tk', tkinter.TkVersion)"

echo "== tests (hardware tests skipped)"
uv run pytest -q

echo "== done: $(git log -1 --format='%h %s')"
