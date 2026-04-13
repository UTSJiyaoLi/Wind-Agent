@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=status"

cd /d "%REPO_ROOT%"
call conda activate rag_task
if errorlevel 1 (
  echo [ERROR] Failed to activate conda env: rag_task
  exit /b 1
)

python scripts\ops\wind_services.py %ACTION%
endlocal

