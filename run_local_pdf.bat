@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo First run: please double-click setup.bat
  pause
  exit /b 1
)
set "PDF=%~1"
if "%PDF%"=="" (
  echo Drag an official Meta India PDF onto this BAT file,
  echo or paste the full PDF path below.
  set /p "PDF=PDF path: "
)
set "PDF=%PDF:"=%"
if not exist "%PDF%" (
  echo.
  echo ERROR: PDF not found:
  echo %PDF%
  pause
  exit /b 1
)
.venv\Scripts\python.exe meta_india.py file --pdf-file "%PDF%"
if errorlevel 1 (
  echo.
  echo Conversion failed. Keep this window open and send the error screenshot.
  pause
  exit /b 1
)
echo.
echo SUCCESS.
echo Excel created at:
echo %CD%\output\meta_india_reports_latest.xlsx
pause
