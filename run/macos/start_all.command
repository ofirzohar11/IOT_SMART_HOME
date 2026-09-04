#!/usr/bin/env bash
#
# Cold Chain Monitor - one window per device (13 processes).
# That is a lot of windows; start_panel.command is easier to work with.
# Double-click this file in Finder, or run it from a terminal.

exec "$(dirname "$0")/_launch.sh" "one window per device" \
    data_manager/data_manager.py \
    gui/main_gui.py \
    emulators/temp_emulator.py \
    emulators/temp_b_emulator.py \
    emulators/ambient_emulator.py \
    emulators/door_emulator.py \
    emulators/badge_emulator.py \
    emulators/power_emulator.py \
    emulators/current_emulator.py \
    emulators/fan_rpm_emulator.py \
    emulators/compressor_emulator.py \
    emulators/fan_emulator.py \
    emulators/siren_emulator.py
