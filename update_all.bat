@echo off
rem Fetch new matches, rebuild the dashboard and open it. Double-click to run.
rem Change START if you want a different first date.
setlocal
cd /d "%~dp0"
set START=2026-01-01

for /f %%d in ('python -c "import datetime;print(datetime.date.today())"') do set TODAY=%%d
if not defined TODAY (
  echo Could not run Python. Check that Python is installed and on your PATH.
  pause
  exit /b 1
)

echo Fetching matches from %START% to %TODAY% ...
python rugby_minutes.py --start %START% --end %TODAY%
if errorlevel 1 (
  echo.
  echo The fetch failed. Scroll up for the error message.
  pause
  exit /b 1
)

echo.
python build_dashboard.py --db rugby.db --out dashboard.html
if errorlevel 1 (
  echo.
  echo The dashboard build failed. Scroll up for the error message.
  pause
  exit /b 1
)

start "" dashboard.html
echo.
echo Done. The dashboard should now be open in your browser.
pause
