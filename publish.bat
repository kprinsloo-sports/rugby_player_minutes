@echo off
rem Rebuild the dashboard from rugby.db and publish it to GitHub Pages.
python build_dashboard.py --db rugby.db --out index.html
if errorlevel 1 exit /b 1
git add index.html
git commit -m "Update dashboard"
git push
