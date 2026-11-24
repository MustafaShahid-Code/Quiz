@echo off
cd /d "%~dp0"
where py >nul 2>nul || (echo Python is not installed. Install it from python.org, tick "Add Python to PATH", then run this again. & pause & exit /b 1)
py -m pip install --upgrade pyserial websocket-client
echo.
echo Setup finished. Next: edit relay_config.txt, then double-click probe.bat
pause
