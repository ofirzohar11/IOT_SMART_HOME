#!/usr/bin/env bash
#
# Cold Chain Monitor - all devices in a single window (3 processes).
# This is the layout to use when recording a demo.
# Double-click this file in Finder, or run it from a terminal.

exec "$(dirname "$0")/_launch.sh" "device panel mode" \
    data_manager/data_manager.py \
    gui/main_gui.py \
    emulators/device_panel.py
