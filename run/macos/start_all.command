#!/usr/bin/env bash
#
# Cold Chain Monitor - one window per device (8 processes).
# Double-click this file in Finder, or run it from a terminal.

exec "$(dirname "$0")/_launch.sh" "one window per device" \
    data_manager/data_manager.py \
    gui/main_gui.py \
    emulators/temp_emulator.py \
    emulators/door_emulator.py \
    emulators/power_emulator.py \
    emulators/compressor_emulator.py \
    emulators/fan_emulator.py \
    emulators/siren_emulator.py
