@echo off
REM Shared launcher used by the .bat files in this folder.
REM Usage:  _launch.bat <script> [<script> ...]
REM
REM Finds the project root, finds a working Python, makes sure the dependencies
REM are installed - offering to install them the first time - and starts every
REM script given to it in its own console window.

setlocal EnableExtensions

REM This file lives in <project>\run\windows, so the root is two levels up.
cd /d "%~dp0..\.."
if errorlevel 1 (
    echo ERROR: could not open the project folder.
    echo   %~dp0..\..
    echo.
    pause
    exit /b 1
)
set "ROOT=%CD%"
set "VENV_PY=%ROOT%\.venv\Scripts\python.exe"

REM --- pick an interpreter --------------------------------------------------
REM A virtual environment in the project takes priority, so the launcher works
REM by double-click without anyone having to activate anything first.
REM
REM Past that, asking for "python" is not enough. That name is on PATH only if
REM the installer's "Add python.exe to PATH" box was ticked, and when it is not,
REM Windows 10 and 11 answer it with the Microsoft Store alias stub - a program
REM that opens the Store and exits without running any code. Testing the
REM candidates by hand would report that as "Python is broken"; what it really
REM means is "try the next name". So each candidate is asked to print its own
REM sys.executable: a stub, a missing command and a failed interpreter all print
REM nothing and are skipped, and what survives is a real absolute path.
REM
REM py -3 comes first because the py launcher is installed by every python.org
REM release and is always on PATH, whether or not that box was ticked.

if defined PYTHON goto have_python
if exist "%VENV_PY%" (
    set "PYTHON=%VENV_PY%"
    goto have_python
)
call :resolve py -3
if defined PYTHON goto have_python
call :resolve python
if defined PYTHON goto have_python
call :resolve python3
if defined PYTHON goto have_python

echo ERROR: Python 3 was not found on this computer.
echo.
echo Install it from https://www.python.org/downloads/windows/
echo and tick "Add python.exe to PATH" on the first screen of the installer.
echo Then run this file again.
echo.
pause
exit /b 1

:have_python

REM --- check the dependencies -----------------------------------------------
"%PYTHON%" -c "import PyQt5, paho.mqtt" >nul 2>&1
if not errorlevel 1 goto ready

echo Cold Chain Monitor - first-time setup
echo.
echo PyQt5 and paho-mqtt are not installed for:
echo   %PYTHON%
echo.
set "REPLY=Y"
set /p "REPLY=Install them into .venv now? [Y/n] "
if /i "%REPLY%"=="n"  goto manual
if /i "%REPLY%"=="no" goto manual

REM Only build an environment when there is not one already: if .venv exists
REM but is missing a package, installing into it is the repair, not replacing it.
if not exist "%VENV_PY%" (
    echo.
    echo creating .venv ...
    "%PYTHON%" -m venv ".venv"
)
if not exist "%VENV_PY%" goto setup_failed
set "PYTHON=%VENV_PY%"

REM A pip too old to read the modern wheel metadata cannot install PyQt5, but a
REM machine that is merely offline for this step is not a reason to stop, so the
REM upgrade is attempted and its result deliberately not checked.
echo.
echo updating pip ...
"%PYTHON%" -m pip install --upgrade pip

echo.
echo installing PyQt5 and paho-mqtt ...
"%PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 goto setup_failed

"%PYTHON%" -c "import PyQt5, paho.mqtt" >nul 2>&1
if errorlevel 1 goto setup_failed

echo.
echo setup finished.
echo.
goto ready

:setup_failed
echo.
echo ERROR: the setup did not finish.
echo.

:manual
echo Set the project up by hand, with these commands:
echo.
echo   cd /d "%ROOT%"
echo   py -3 -m venv .venv
echo   .venv\Scripts\python -m pip install -r requirements.txt
echo.
echo If .venv already exists and is damaged, delete it first.
echo.
pause
exit /b 1

:ready
echo Cold Chain Monitor
echo project : %ROOT%
echo python  : %PYTHON%
echo.

REM --- launch ---------------------------------------------------------------
:loop
if "%~1"=="" goto done
echo   -^> %~1
start "Cold Chain: %~1" "%PYTHON%" "%~1"
call :pause_one
shift
goto loop

:done
echo.
echo All components started. Close each window to stop it.
call :pause_one
call :pause_one
call :pause_one
endlocal
exit /b 0

REM --- subroutines ----------------------------------------------------------

REM Ask a candidate interpreter to print its own path, and keep it only if what
REM came back is a file that exists. See the note above have_python.
:resolve
for /f "delims=" %%I in ('%* -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON=%%I"
if defined PYTHON if not exist "%PYTHON%" set "PYTHON="
goto :eof

REM One second, so thirteen processes do not all reach the broker in the same
REM instant. timeout refuses to run when stdin is redirected - which is what
REM happens if these launchers are themselves driven by a script - so ping
REM stands in for it there.
:pause_one
timeout /t 1 /nobreak >nul 2>&1 || ping -n 2 127.0.0.1 >nul 2>&1
goto :eof
