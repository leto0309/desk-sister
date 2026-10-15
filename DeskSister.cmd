@echo off
rem Starts Desk Sister without a console window.
cd /d "%~dp0"
rem Imports the native modules the app really loads, not just the top-level packages.
set "CHECK=import PySide6.QtCore, PySide6.QtGui, PySide6.QtWidgets, PIL.Image, anthropic"
if not exist ".venv\Scripts\python.exe" (
  echo First run: creating .venv...
  python -m venv .venv || goto :fail
)
rem Checked on every start, so a failed or interrupted install is repaired instead of skipped.
".venv\Scripts\python.exe" -c "%CHECK%" >nul 2>&1 && goto :run
echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install --force-reinstall -r requirements.txt || goto :fail
".venv\Scripts\python.exe" -c "%CHECK%" || goto :fail
:run
start "" ".venv\Scripts\pythonw.exe" app.py
exit /b 0
:fail
echo Setup failed. Python 3.11+ and network access are required.
pause
exit /b 1
