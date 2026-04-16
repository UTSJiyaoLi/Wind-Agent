@echo off
setlocal

set "ROOT_DIR=%~dp0"
set "WEB_DIR=%ROOT_DIR%apps\web"
if not defined UI_PORT set "UI_PORT=3005"

if not defined LOCAL_PORT set "LOCAL_PORT=8787"
if not defined REMOTE_HOST set "REMOTE_HOST=127.0.0.1"
if not defined REMOTE_PORT set "REMOTE_PORT=8787"

set "JUMP_USER=lijiyao"
set "JUMP_HOST=172.30.3.166"
set "TARGET_USER=lijiyao"
set "TARGET_HOST=gpu6000"
set "SSH_PASSWORD=Ljy05163417"

set "TUNNEL_TITLE=wind-agent-chatui-tunnel-%LOCAL_PORT%"
set "WEB_TITLE=wind-agent-chatui-next-%UI_PORT%"
set "WEB_BOOT=%ROOT_DIR%tmp_start_react_next_chatui.cmd"
set "TUNNEL_BOOT=%ROOT_DIR%tmp_start_react_tunnel.cmd"

if not exist "%WEB_DIR%\package.json" (
  echo [ERROR] Missing frontend project: %WEB_DIR%\package.json
  if not defined NO_PAUSE pause
  exit /b 1
)

set "NPM_CMD="
for /f "delims=" %%N in ('where npm.cmd 2^>nul') do (
  set "NPM_CMD=%%N"
  goto :npm_found
)
if exist "C:\Program Files\nodejs\npm.cmd" set "NPM_CMD=C:\Program Files\nodejs\npm.cmd"

:npm_found
if not defined NPM_CMD (
  echo [ERROR] npm.cmd not found. Please install Node.js.
  if not defined NO_PAUSE pause
  exit /b 1
)

echo [INFO] Launch config:
echo        UI_PORT=%UI_PORT%
echo        LOCAL_PORT=%LOCAL_PORT%
echo        REMOTE_HOST=%REMOTE_HOST%
echo        REMOTE_PORT=%REMOTE_PORT%
echo [INFO] For colleague: use different UI_PORT/LOCAL_PORT on their own machine.

if /I not "%SKIP_TUNNEL%"=="1" (
  where plink.exe >nul 2>nul
  if not errorlevel 1 (
    (
      echo @echo off
      echo plink -ssh -batch -pw "%SSH_PASSWORD%" -proxycmd "plink -ssh -batch -pw \"%SSH_PASSWORD%\" %JUMP_USER%@%JUMP_HOST% -nc %%%%host:%%%%port" -L %LOCAL_PORT%:%REMOTE_HOST%:%REMOTE_PORT% %TARGET_USER%@%TARGET_HOST%
    ) > "%TUNNEL_BOOT%"
    start "%TUNNEL_TITLE%" cmd /k ""%TUNNEL_BOOT%""
  ) else (
    where ssh >nul 2>nul
    if not errorlevel 1 (
      echo [WARN] plink not found, fallback to OpenSSH. Password may need manual input.
      start "%TUNNEL_TITLE%" cmd /k "ssh -L %LOCAL_PORT%:%REMOTE_HOST%:%REMOTE_PORT% -J %JUMP_USER%@%JUMP_HOST% %TARGET_USER%@%TARGET_HOST%"
    ) else (
      echo [WARN] Neither plink nor ssh found, skip tunnel.
    )
  )
)

(
  echo @echo off
  echo cd /d "%WEB_DIR%"
  echo if not exist node_modules call "%NPM_CMD%" install
  echo set NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:%LOCAL_PORT%
  echo call "%NPM_CMD%" run dev -- -p %UI_PORT%
) > "%WEB_BOOT%"

echo [INFO] Starting Next.js ChatUI on port %UI_PORT% ...
start "%WEB_TITLE%" cmd /k ""%WEB_BOOT%""

echo [INFO] Waiting for ChatUI page...
powershell -NoProfile -Command "$ok=$false; for($i=0; $i -lt 120; $i++){ try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:%UI_PORT%/' -TimeoutSec 2; if($r.StatusCode -ge 200){ $ok=$true; break } } catch {}; Start-Sleep -Seconds 1 }; if($ok){ exit 0 } else { exit 1 }"
if errorlevel 1 (
  echo [ERROR] Next.js page / not reachable.
  echo [ERROR] Check window: %WEB_TITLE%
  if not defined NO_PAUSE pause
  exit /b 1
)

echo [OK] Open: http://127.0.0.1:%UI_PORT%/
start "" "http://127.0.0.1:%UI_PORT%/"
powershell -NoProfile -Command "Start-Process 'http://127.0.0.1:%UI_PORT%/'" >nul 2>nul

echo [DONE] ChatUI started.
if /I "%SKIP_TUNNEL%"=="1" echo [INFO] Tunnel skipped by SKIP_TUNNEL=1.
if not defined NO_PAUSE pause
exit /b 0
