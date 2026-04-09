@echo off
setlocal

rem One-click launcher for docs\langchain_generative_ui_v1.html
rem local browser -> localhost:8787 tunnel -> lijiyao jump -> gpu6000:127.0.0.1:8787

set "JUMP_HOST=lijiyao@172.30.3.166"
set "TARGET_HOST=lijiyao@gpu6000"
set "LOCAL_PORT=8787"
set "REMOTE_HOST=127.0.0.1"
set "REMOTE_PORT=8787"
set "TUNNEL_TITLE=wind-langchain-ui-v1-tunnel-8787"

set "REPO_ROOT=%~dp0"
set "HTML_PATH=%REPO_ROOT%docs\langchain_generative_ui_v1.html"

if not exist "%HTML_PATH%" (
  echo [ERROR] Web UI file not found: %HTML_PATH%
  exit /b 1
)

echo [1/2] Starting SSH tunnel in new window...
start "%TUNNEL_TITLE%" cmd /k "ssh -L %LOCAL_PORT%:%REMOTE_HOST%:%REMOTE_PORT% -J %JUMP_HOST% %TARGET_HOST%"

echo [2/2] Opening local web page...
timeout /t 2 /nobreak >nul
start "" "%HTML_PATH%"

echo.
echo Done.
echo - Keep the "%TUNNEL_TITLE%" window open while using the page.
echo - In the UI, Backend URL should stay: http://127.0.0.1:8787

endlocal
