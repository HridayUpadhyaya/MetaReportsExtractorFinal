@echo off
cd /d "%~dp0"
py -3.12 -m venv .venv 2>nul || py -m venv .venv
if errorlevel 1 (
  echo Python was not found. Install Python 3.11 or 3.12 from python.org, then rerun this file.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
  echo Dependency installation failed.
  pause
  exit /b 1
)
REM Prefer the user's installed Chrome, but install Chromium as a fallback.
.venv\Scripts\python.exe -m playwright install chromium
if errorlevel 1 (
  echo Playwright browser installation failed. Google Chrome may still work, but rerun setup if sync cannot launch a browser.
)
echo Setup complete.
pause
