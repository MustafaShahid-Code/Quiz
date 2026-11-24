@echo off
cd /d "%~dp0"
:loop
py fq_relay.py
echo Relay stopped. Restarting in 5 seconds (close this window to quit)...
timeout /t 5 >nul
goto loop
