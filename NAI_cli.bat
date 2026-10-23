@echo off
setlocal
cd /d "%~dp0"
echo Starting NAI CLI (Qwen2.5-1.5B, offline)...
".venv\Scripts\python.exe" run_nai_cli.py %*
endlocal
