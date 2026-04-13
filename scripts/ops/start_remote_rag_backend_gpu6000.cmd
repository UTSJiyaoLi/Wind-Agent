@echo off
setlocal

rem Backward-compatible wrapper:
rem start/ensure all wind-* services via unified manager (whitelist only).

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%"

call conda activate rag_task
if errorlevel 1 (
  echo [ERROR] Failed to activate conda env: rag_task
  exit /b 1
)

echo Starting/ensuring wind services on gpu6000 ...
python scripts\ops\wind_services.py start
if errorlevel 1 (
  echo [ERROR] failed to start wind services.
  exit /b 1
)

python scripts\ops\wind_services.py health
echo Wind services started.
echo Next step: run scripts\ops\start_rag_web_local.cmd

endlocal
