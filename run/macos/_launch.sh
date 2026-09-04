#!/usr/bin/env bash
#
# Shared launcher used by the .command files in this folder.
# Usage:  _launch.sh "<description>" <script> [<script> ...]
#
# Finds the project root, picks an interpreter, starts every script given to it
# in the background, and stops them all together on Ctrl-C or when the window is
# closed.

set -uo pipefail

DESCRIPTION="$1"
shift

# This file lives in <project>/run/macos, so the project root is two levels up.
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

# --- pick an interpreter ----------------------------------------------------
# A virtual environment in the project takes priority, so the launcher works by
# double-click without anyone having to activate anything first.
if [ -n "${PYTHON:-}" ]; then
    :
elif [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
else
    echo "ERROR: Python 3 was not found."
    echo "Install Python 3, then see RUNNING.md for the setup steps."
    read -r -p "Press Return to close..."
    exit 1
fi

# --- check the dependencies -------------------------------------------------
if ! "$PYTHON" -c "import PyQt5, paho.mqtt" >/dev/null 2>&1; then
    echo "ERROR: PyQt5 and paho-mqtt are not installed for $PYTHON"
    echo ""
    echo "Set them up once with:"
    echo "  cd \"$PROJECT_ROOT\""
    echo "  python3 -m venv .venv"
    echo "  .venv/bin/pip install -r requirements.txt"
    echo ""
    read -r -p "Press Return to close..."
    exit 1
fi

# --- launch -----------------------------------------------------------------
pids=()

cleanup() {
    echo ""
    echo "stopping all components..."
    for pid in "${pids[@]:-}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Cold Chain Monitor - $DESCRIPTION"
echo "project : $PROJECT_ROOT"
echo "python  : $PYTHON"
echo ""

for script in "$@"; do
    echo "  -> $script"
    "$PYTHON" "$script" &
    pids+=($!)
    sleep 1
done

echo ""
echo "${#pids[@]} components running. Press Ctrl-C to stop them all."
wait
