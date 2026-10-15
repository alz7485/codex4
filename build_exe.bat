@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 goto error
)
".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 goto error
".venv\Scripts\python.exe" build_exe.py
if errorlevel 1 goto error
echo.
echo Build completed: dist\OutlookMailDesk\OutlookMailDesk.exe
echo Distribute dist\OutlookMailDesk-windows-onedir.zip to other PCs.
pause
exit /b 0
:error
echo.
echo Build failed. Check the error above.
pause
exit /b 1
