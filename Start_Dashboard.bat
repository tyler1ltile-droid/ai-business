@echo off
setlocal
cd /d "%~dp0"

echo Starting 1L Lead Engine Dashboard...
echo.
echo This opens the local dashboard at:
echo http://127.0.0.1:8787
echo.
echo Close the dashboard server window when you are done.
echo.

start "1L Lead Dashboard Server" "%~dp0Run_Dashboard_Server.bat"
timeout /t 2 /nobreak > nul
start "" "http://127.0.0.1:8787"

endlocal
