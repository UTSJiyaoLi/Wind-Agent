@echo off
setlocal

rem One-click launcher:
rem 1) Start SSH local forward in a new cmd window (keeps running)
rem 2) Open local RAG web HTML in default browser

set "JUMP_HOST=lijiyao@172.30.3.166"
set "TARGET_HOST=lijiyao@gpu6000"
set "LOCAL_PORT=8787"
set "REMOTE_HOST=127.0.0.1"
set "REMOTE_PORT=8787"

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
set "HTML_PATH=%REPO_ROOT%\docs\local_rag_web.html"

echo [1/2] Starting SSH tunnel in new window...
start "RAG Tunnel 8787" cmd /k "ssh -L %LOCAL_PORT%:%REMOTE_HOST%:%REMOTE_PORT% -J %JUMP_HOST% %TARGET_HOST%"

echo [2/2] Opening local web page...
timeout /t 2 /nobreak >nul
start "" "%HTML_PATH%"

echo.
echo Done.
echo - Keep the "RAG Tunnel 8787" window open while using the web page.
echo - In web page, set:
echo   Mode = RAG
echo   RAG Backend URL = http://127.0.0.1:8787

endlocal
