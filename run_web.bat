@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo First run: please run setup.bat
  pause
  exit /b 1
)
start "Meta India Extractor" http://127.0.0.1:8000
.venv\Scripts\python.exe web_app.py
