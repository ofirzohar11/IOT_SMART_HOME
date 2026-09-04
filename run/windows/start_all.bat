@echo off
REM Cold Chain Monitor - one window per device (13 processes).
REM That is a lot of windows; start_panel.bat is easier to work with.
REM Double-click this file, or run it from a command prompt.

call "%~dp0_launch.bat" ^
    data_manager\data_manager.py ^
    gui\main_gui.py ^
    emulators\temp_emulator.py ^
    emulators\temp_b_emulator.py ^
    emulators\ambient_emulator.py ^
    emulators\door_emulator.py ^
    emulators\badge_emulator.py ^
    emulators\power_emulator.py ^
    emulators\current_emulator.py ^
    emulators\fan_rpm_emulator.py ^
    emulators\compressor_emulator.py ^
    emulators\fan_emulator.py ^
    emulators\siren_emulator.py
