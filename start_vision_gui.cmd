@echo off
cd /d "%~dp0"
if not exist ".venv-vision\Scripts\python.exe" (
  echo Run setup_vision_env.cmd first.
  pause
  exit /b 1
)
".venv-vision\Scripts\python.exe" scripts/vision_preflight.py
if errorlevel 1 (
  pause
  exit /b 1
)
".venv-vision\Scripts\python.exe" main.py
if errorlevel 1 pause
