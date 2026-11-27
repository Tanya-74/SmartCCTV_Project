@echo off
rem One-click Smart CCTV demo with screen recording. Double-click this file.
rem Optional arguments are passed on, e.g.:  run_demo.bat --live-seconds 20
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" goto no_venv
if not exist "data\videos\Assault001_x264.mp4" goto no_video

rem Reopen in a classic console window, so it can be placed next to the browser.
if defined SMARTCCTV_DEMO_CHILD goto run
set "SMARTCCTV_DEMO_CHILD=1"
start "Smart CCTV demo" conhost.exe cmd.exe /c call "%~f0" %*
exit /b 0

:run
title Smart CCTV demo
".venv\Scripts\python.exe" scripts\run_demo.py %*
set "RC=%ERRORLEVEL%"
echo.
if not defined DEMO_NOPAUSE pause
exit /b %RC%

:no_venv
echo.
echo  STOPPED: the Python environment .venv was not found in
echo  %~dp0
echo  Create it first:
echo     python -m venv .venv
echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
goto fail

:no_video
echo.
echo  STOPPED: the sample video is missing:
echo  %~dp0data\videos\Assault001_x264.mp4
echo  Download the dataset sample first (see README.md).
goto fail

:fail
echo.
if not defined DEMO_NOPAUSE pause
exit /b 1
