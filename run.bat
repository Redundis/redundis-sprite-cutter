@echo off
REM Starts Redundis Sprite Cutter. Installs the Python packages the first time.
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3 from https://www.python.org/downloads/ and check "Add python.exe to PATH".
  pause
  exit /b 1
)
python -c "import customtkinter, PIL, numpy, pillow_heif, tkinterdnd2" 1>nul 2>nul
if errorlevel 1 (
  echo Installing required packages...
  python -m pip install -r "%~dp0requirements.txt"
  if errorlevel 1 (
    echo Could not install packages.
    pause
    exit /b 1
  )
)
REM pyw / pythonw open the cutter with no Command Prompt, then this window closes.
where pyw >nul 2>nul
if not errorlevel 1 (
  start "" pyw -3 "%~dp0app.py"
  exit /b 0
)
where pythonw >nul 2>nul
if not errorlevel 1 (
  start "" pythonw "%~dp0app.py"
  exit /b 0
)
python "%~dp0app.py"
if errorlevel 1 pause
