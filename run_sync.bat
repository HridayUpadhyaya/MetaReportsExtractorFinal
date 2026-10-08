@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo First run: please run setup.bat
  pause
  exit /b 1
)
echo Opening Meta once in Chrome. This version does NOT call the Meta hub with Python requests.
.venv\Scripts\python.exe meta_india.py sync --max-new 15
pause
