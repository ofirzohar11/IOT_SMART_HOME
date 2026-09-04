@echo off
REM Cold Chain Monitor - all devices in a single window (3 processes).
REM This is the layout to use when recording a demo.
REM Double-click this file, or run it from a command prompt.

call "%~dp0_launch.bat" ^
    data_manager\data_manager.py ^
    gui\main_gui.py ^
    emulators\device_panel.py
