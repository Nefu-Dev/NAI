@echo off
rem NAI dev launcher (runs from source, no EXE).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo venv not found. Run build.bat full first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" run_nai.py
