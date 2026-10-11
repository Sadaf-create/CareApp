@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m streamlit run app.py --server.address 0.0.0.0
pause
exit /b
:failed
 echo Setup failed. Install Python 3.11 or newer and check your internet connection.
pause
