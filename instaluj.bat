@echo off
setlocal
cd /d "%~dp0"
title Installing Mysttic Audition
echo Installing Mysttic Audition: Python environment and dependencies. This takes a few minutes.
echo.
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv 2>nul || python -m venv .venv || goto :error
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt || goto :error
echo.
echo Done. The app will start in a moment.
timeout /t 3 >nul
exit /b 0

:error
echo.
echo Installation failed. Python 3.10 or newer is required (python.org).
pause
exit /b 1
