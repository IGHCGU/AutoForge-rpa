@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 正在创建项目独立运行环境……
  python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
  echo 无法创建运行环境，请确认已经安装 64 位 Python 3.10-3.12。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install --prefer-binary -r requirements-ocr.txt
if errorlevel 1 (
  echo.
  echo 安装失败，请检查 Python 3.10-3.12 和网络连接。
  pause
  exit /b 1
)
echo.
echo 安装完成，可以双击“启动.bat”。
pause
