#!/usr/bin/env bash
# Start the Cold Chain Monitor (macOS / Linux). Ctrl-C stops everything.
#
#   ./start_all.sh            8 processes, one window per device
#   ./start_all.sh --panel    3 processes, all devices in a single window
#
# Both modes open the same six MQTT client connections; only the window layout
# differs. Set PYTHON to use a virtual environment:
#
#   PYTHON="$PWD/.venv/bin/python" ./start_all.sh

set -uo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
MODE="${1:-separate}"
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

case "$MODE" in
    --panel|-p|panel)
        launch emulators/device_panel.py
        echo ""
        echo "3 processes running (device panel mode). Press Ctrl-C to stop."
        ;;
    *)
        launch emulators/temp_emulator.py
        launch emulators/door_emulator.py
        launch emulators/power_emulator.py
        launch emulators/compressor_emulator.py
        launch emulators/fan_emulator.py
        launch emulators/siren_emulator.py
        echo ""
        echo "8 processes running. Press Ctrl-C to stop."
        echo "Tip: ./start_all.sh --panel puts every device in one window instead."
        ;;
esac

wait
