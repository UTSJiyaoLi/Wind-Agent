@echo off
setlocal

rem One-click launcher for local offline trace viewer.
rem It activates conda env `rag_task` and runs streamlit app.

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
set "VIEWER_PY=%REPO_ROOT%\scripts\ops\trace_jsonl_viewer.py"
set "TRACE_DIR=%REPO_ROOT%\storage\traces"
set "REMOTE_TRACE_DIR=%REPO_ROOT%\artifacts\remote_traces"
set "JUMP_HOST=lijiyao@172.30.3.166"
set "TARGET_HOST=lijiyao@gpu6000"
set "REMOTE_PATH=/share/home/lijiyao/CCCC/Wind-Agent/storage/traces/"

if not exist "%VIEWER_PY%" (
  echo [ERROR] Viewer script not found: %VIEWER_PY%
  exit /b 1
)

echo Starting local trace viewer...
echo - Repo: %REPO_ROOT%
echo - Local trace dir: %TRACE_DIR%
echo - Remote sync dir: %REMOTE_TRACE_DIR%
echo.

call conda activate rag_task
if errorlevel 1 (
  echo [ERROR] Failed to activate conda env: rag_task
  echo Please run this script in a shell where conda is initialized.
  exit /b 1
)

cd /d "%REPO_ROOT%"

if not exist "%REMOTE_TRACE_DIR%" mkdir "%REMOTE_TRACE_DIR%"
echo [Sync] Pulling traces from gpu6000...
scp -r -o ProxyJump=%JUMP_HOST% %TARGET_HOST%:%REMOTE_PATH%* "%REMOTE_TRACE_DIR%\" >nul 2>nul
if errorlevel 1 (
  echo [WARN] Remote trace sync failed, fallback to local trace dir.
  set "VIEW_TRACE_DIR=%TRACE_DIR%"
) else (
  echo [OK] Remote traces synced.
  set "VIEW_TRACE_DIR=%REMOTE_TRACE_DIR%"
)

streamlit run scripts\ops\trace_jsonl_viewer.py -- --trace-dir "%VIEW_TRACE_DIR%"

endlocal
