@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title NAI one-click build

rem ============================================================
rem  NAI (Nefu AI) one-click build -> dist\NAI.exe
rem  Usage:
rem    build.bat         fast rebuild: if models\nai.gguf exists, only repackage the EXE
rem    build.bat full    full pipeline: dataset -> fine-tune -> GGUF -> EXE
rem ============================================================

if /i "%~1"=="full" goto full
if exist "models\nai.gguf" goto package
:full

if exist ".venv\Scripts\python.exe" goto deps
echo [NAI] creating Python 3.11 venv...
py -3.11 -m venv .venv

:deps
echo [NAI] installing torch (CPU)...
".venv\Scripts\python.exe" -m pip install torch --index-url https://download.pytorch.org/whl/cpu
echo [NAI] installing other dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
if errorlevel 1 ( echo [NAI] dependency install failed & pause & exit /b 1 )

echo [NAI] building dataset...
".venv\Scripts\python.exe" dataset\make_dataset.py
if errorlevel 1 ( echo [NAI] dataset failed & pause & exit /b 1 )

echo [NAI] fine-tuning (CPU, this can take several minutes)...
".venv\Scripts\python.exe" -u train.py
if errorlevel 1 ( echo [NAI] training failed & pause & exit /b 1 )

echo [NAI] converting to quantized GGUF...
".venv\Scripts\python.exe" make_gguf.py
if errorlevel 1 ( echo [NAI] gguf failed & pause & exit /b 1 )

:package
echo [NAI] making icon...
".venv\Scripts\python.exe" assets\make_icon.py

echo [NAI] building NAI.exe with PyInstaller...
".venv\Scripts\python.exe" build_exe.py
if errorlevel 1 ( echo [NAI] packaging failed & pause & exit /b 1 )

echo.
echo ============================================================
echo  Done: dist\NAI.exe
echo  Run:  dist\NAI.exe            (GUI terminal)
echo  Test: dist\NAI.exe --selftest (headless check -> selftest_result.json)
echo ============================================================
pause
