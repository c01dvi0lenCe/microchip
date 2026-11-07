@echo off
cd /d "%~dp0"
if not exist ".venv-vision\Scripts\python.exe" (
  py -3.14 -m venv .venv-vision
  if errorlevel 1 goto error
)
".venv-vision\Scripts\python.exe" -m pip install -r requirements-vision.txt --extra-index-url https://download.pytorch.org/whl/cu128
if errorlevel 1 goto error
echo Vision environment installed. Copy the model package to models\g4_unet.
pause
exit /b 0
:error
echo Setup failed. Install 64-bit Python 3.14 and check network access.
pause
exit /b 1
