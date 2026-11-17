@echo off
cd /d "%~dp0"
if not exist ".venv-vision\Scripts\python.exe" (
  py -3.14 -m venv .venv-vision
  if errorlevel 1 goto error
)
".venv-vision\Scripts\python.exe" -m pip install -r requirements-vision.txt --extra-index-url https://download.pytorch.org/whl/cu128
if errorlevel 1 goto error
".venv-vision\Scripts\python.exe" -m pip check
if errorlevel 1 goto error
echo Vision dependencies installed. Model and MVS camera SDK are separate.
echo G4 model: https://github.com/c01dvi0lenCe/microchip/releases/tag/g4-unet-inference-v1
echo For the checksum, extraction and offline test see docs\camera-pc-quickstart.md
pause
exit /b 0
:error
echo Setup failed. Install 64-bit Python 3.14 and check network access.
pause
exit /b 1
