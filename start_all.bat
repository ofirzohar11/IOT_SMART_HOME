@echo off
REM Start every component of the Cold Chain Monitor (Windows).
cd /d "%~dp0"

echo Cold Chain Monitor - starting components

start "Data Manager"      python data_manager\data_manager.py
timeout /t 2 /nobreak > nul
start "Main GUI"          python gui\main_gui.py
timeout /t 1 /nobreak > nul
start "Temp Sensor"       python emulators\temp_emulator.py
timeout /t 1 /nobreak > nul
start "Door Sensor"       python emulators\door_emulator.py
timeout /t 1 /nobreak > nul
start "Power Sensor"      python emulators\power_emulator.py
timeout /t 1 /nobreak > nul
start "Compressor Relay"  python emulators\compressor_emulator.py
timeout /t 1 /nobreak > nul
start "Fan Relay"         python emulators\fan_emulator.py
timeout /t 1 /nobreak > nul
start "Siren Relay"       python emulators\siren_emulator.py

echo All 8 components started.
