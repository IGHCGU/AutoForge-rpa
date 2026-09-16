@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" main.py
  exit /b 0
)
python main.py
if errorlevel 1 pause
