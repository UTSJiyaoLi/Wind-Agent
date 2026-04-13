@echo off
setlocal ENABLEDELAYEDEXPANSION

rem Robust launcher for langchain_generative_ui_v1.html
rem Supports html in current folder OR .\docs\

set "SCRIPT_DIR=%~dp0"
set "HTML_PATH=%SCRIPT_DIR%langchain_generative_ui_v1.html"
if not exist "%HTML_PATH%" set "HTML_PATH=%SCRIPT_DIR%docs\langchain_generative_ui_v1.html"

set "JUMP_HOST=lijiyao@172.30.3.166"
set "TARGET_HOST=lijiyao@gpu6000"
set "LOCAL_PORT=8787"
set "REMOTE_HOST=127.0.0.1"
set "REMOTE_PORT=8787"
set "TUNNEL_TITLE=wind-langchain-ui-v1-tunnel-%LOCAL_PORT%"

if not exist "%HTML_PATH%" (
  echo [ERROR] Cannot find langchain_generative_ui_v1.html
  echo [ERROR] Tried:
  echo   %SCRIPT_DIR%langchain_generative_ui_v1.html
  echo   %SCRIPT_DIR%docs\langchain_generative_ui_v1.html
  pause
  exit /b 1
)

where ssh >nul 2>nul
if errorlevel 1 (
  echo [ERROR] ssh not found. Please install OpenSSH client first.
  pause
  exit /b 1
)

echo [INFO] HTML: %HTML_PATH%
echo [INFO] Tunnel: localhost:%LOCAL_PORT% ^<-> %TARGET_HOST%:%REMOTE_PORT% (jump: %JUMP_HOST%)

echo [1/2] Starting SSH tunnel window...
start "%TUNNEL_TITLE%" cmd /k "ssh -L %LOCAL_PORT%:%REMOTE_HOST%:%REMOTE_PORT% -J %JUMP_HOST% %TARGET_HOST%"
if errorlevel 1 (
  echo [ERROR] Failed to start SSH tunnel window.
  pause
  exit /b 1
)

timeout /t 2 /nobreak >nul

echo [2/2] Opening frontend...
start "" "%HTML_PATH%"
if errorlevel 1 (
  echo [ERROR] Failed to open HTML.
  pause
  exit /b 1
)

echo.
echo [DONE] Keep the "%TUNNEL_TITLE%" window open.
echo [DONE] Backend URL in UI: http://127.0.0.1:%LOCAL_PORT%
pause
exit /b 0
