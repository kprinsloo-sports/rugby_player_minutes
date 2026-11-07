@echo off
rem Rebuild dashboard.html from rugby.db (no fetching) and open it.
setlocal
cd /d "%~dp0"
python build_dashboard.py --db rugby.db --out dashboard.html
if errorlevel 1 (
  echo.
  echo The dashboard build failed. Scroll up for the error message.
  pause
  exit /b 1
)
start "" dashboard.html
echo.
echo Done.
pause
