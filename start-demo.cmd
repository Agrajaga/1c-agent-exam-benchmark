@echo off
rem Starts the local stand and opens http://127.0.0.1:8879/. Needs Python 3.11+.
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (where py >nul 2>nul && (set "PY=py -3") || set "PY=python")
%PY% -X utf8 "%~dp0tools\start_demo.py"
if errorlevel 1 (
  echo.
  echo Python 3.11+ is required: https://www.python.org/downloads/  or  winget install Python.Python.3.12
  pause
)
