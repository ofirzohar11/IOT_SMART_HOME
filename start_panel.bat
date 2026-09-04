@echo off
REM Start the Cold Chain Monitor with every device in a single window (Windows).
REM Three processes instead of eight; the MQTT connections are identical.
cd /d "%~dp0"

echo Cold Chain Monitor - device panel mode

start "Data Manager" python data_manager\data_manager.py
timeout /t 2 /nobreak > nul
start "Main GUI"     python gui\main_gui.py
timeout /t 1 /nobreak > nul
start "Device Panel" python emulators\device_panel.py

echo 3 components started.
