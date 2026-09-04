#!/usr/bin/env bash
# Start every component of the Cold Chain Monitor (macOS / Linux).
# Ctrl-C stops all of them.

set -uo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
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

launch() {
    echo "  -> $1"
    "$PYTHON" "$1" &
    pids+=($!)
    sleep 1
}

echo "Cold Chain Monitor - starting components"
launch data_manager/data_manager.py
launch gui/main_gui.py
launch emulators/temp_emulator.py
launch emulators/door_emulator.py
launch emulators/power_emulator.py
launch emulators/compressor_emulator.py
launch emulators/fan_emulator.py
launch emulators/siren_emulator.py

echo ""
echo "All 8 components running. Press Ctrl-C to stop."
wait
