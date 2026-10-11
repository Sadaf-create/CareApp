@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
 echo Run start_windows.bat first.
 pause
 exit /b
)
.venv\Scripts\python.exe worker.py
pause
