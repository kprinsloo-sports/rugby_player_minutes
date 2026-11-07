@echo off
rem Show the players with the most minutes per position and save minutes_by_position.csv.
setlocal
cd /d "%~dp0"
python analysis.py --top 10 --csv minutes_by_position.csv
echo.
pause
