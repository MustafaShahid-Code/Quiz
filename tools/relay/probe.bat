@echo off
cd /d "%~dp0"
py fq_relay.py --probe
echo.
echo Send the file probe_report.txt to the remote engineer if anything above says FAILED or WARNING.
pause
