@echo off
cd /d "C:\wind-agent\apps\web"
if not exist node_modules call "C:\Program Files\nodejs\npm.cmd" install
set NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8787
call "C:\Program Files\nodejs\npm.cmd" run dev -- -p 3005
