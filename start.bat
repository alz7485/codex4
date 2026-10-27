@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run setup.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" main.py --check-dependencies
if not errorlevel 1 goto launch
echo Required packages are missing or broken. Repairing this app's Python environment...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto error
".venv\Scripts\python.exe" main.py --check-dependencies
if errorlevel 1 goto error
:launch
".venv\Scripts\python.exe" main.py
if errorlevel 1 goto error
exit /b 0
:error
echo Startup failed. Check the message above or run setup.bat again.
pause
exit /b 1
