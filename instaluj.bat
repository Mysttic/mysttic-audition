@echo off
setlocal
cd /d "%~dp0"
title Instalacja mysttic-audition
echo Instalacja mysttic-audition: srodowisko Pythona i zaleznosci. To potrwa kilka minut.
echo.
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv 2>nul || python -m venv .venv || goto :error
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt || goto :error
echo.
echo Gotowe, aplikacja zaraz sie uruchomi.
timeout /t 3 >nul
exit /b 0

:error
echo.
echo Instalacja nie powiodla sie. Potrzebny jest Python 3.10 lub nowszy (python.org).
pause
exit /b 1
