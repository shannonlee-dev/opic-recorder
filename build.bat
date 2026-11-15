@echo off
setlocal
rem pushd supports a WSL UNC project path by allocating a temporary drive.
pushd "%~dp0"
if errorlevel 1 goto location_error

py -3 -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ is required'" >nul 2>&1
if errorlevel 1 goto python_error
if not exist ".venv-win\Scripts\python.exe" (
    py -3 -m venv .venv-win
    if errorlevel 1 goto failed
    if not errorlevel 0 goto failed
)
set "OPIC_PYTHON=.venv-win\Scripts\python.exe"
"%OPIC_PYTHON%" -m pip install -r requirements.txt
if not "%errorlevel%"=="0" goto failed
"%OPIC_PYTHON%" -m unittest discover -s tests -v
if not "%errorlevel%"=="0" goto failed
"%OPIC_PYTHON%" -m PyInstaller --noconfirm --clean --onefile --windowed --noupx --name OPIc_Recorder --icon assets\opic-recorder.ico --add-data "assets\opic-recorder.ico;assets" --hidden-import _cffi_backend --collect-all _sounddevice_data main.py
if not "%errorlevel%"=="0" goto failed
if not exist "dist\OPIc_Recorder.exe" goto failed

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-shortcut.ps1" -ExecutablePath "%~dp0dist\OPIc_Recorder.exe"
if errorlevel 1 goto shortcut_error
echo.
echo Build succeeded: %~dp0dist\OPIc_Recorder.exe
echo Installed app and desktop shortcut: OPIc Voice Recorder
popd
if /i not "%~1"=="--no-pause" pause
exit /b 0

:python_error
echo ERROR: Install Windows Python 3.11 or newer with the Python launcher and Tcl/Tk.
goto failed
:shortcut_error
echo ERROR: EXE was built, but shortcut installation failed. Close the app and retry.
goto failed
:failed
echo ERROR: Build or installation failed. See the error above.
popd
if /i not "%~1"=="--no-pause" pause
exit /b 1
:location_error
echo ERROR: Cannot access the project folder.
if /i not "%~1"=="--no-pause" pause
exit /b 1
