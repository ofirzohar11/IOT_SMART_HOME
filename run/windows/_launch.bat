@echo off
REM Shared launcher used by the .bat files in this folder.
REM Usage:  _launch.bat <script> [<script> ...]
REM
REM Finds the project root, picks an interpreter, and starts every script given
REM to it in its own console window.

setlocal

REM This file lives in <project>\run\windows, so the root is two levels up.
cd /d "%~dp0..\.."

REM --- pick an interpreter --------------------------------------------------
REM A virtual environment in the project takes priority, so the launcher works
REM by double-click without anyone having to activate anything first.
if defined PYTHON goto have_python
if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
    goto have_python
)
set "PYTHON=python"
:have_python

REM --- check the dependencies -----------------------------------------------
"%PYTHON%" -c "import PyQt5, paho.mqtt" >nul 2>&1
if errorlevel 1 (
    echo ERROR: PyQt5 and paho-mqtt are not installed for %PYTHON%
    echo.
    echo Set them up once with:
    echo   cd /d "%CD%"
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo Cold Chain Monitor
echo project : %CD%
echo python  : %PYTHON%
echo.

REM --- launch ---------------------------------------------------------------
:loop
if "%~1"=="" goto done
echo   -^> %~1
start "Cold Chain: %~1" "%PYTHON%" "%~1"
timeout /t 1 /nobreak >nul
shift
goto loop

:done
echo.
echo All components started. Close each window to stop it.
timeout /t 3 /nobreak >nul
