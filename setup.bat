@echo off
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto error
".venv\Scripts\python.exe" main.py --check-dependencies
if errorlevel 1 goto error
echo Setup completed. Run start.bat to launch the app.
pause
exit /b 0
:error
echo Setup failed. Install Python 3.11 or later and check the message above.
pause
exit /b 1
