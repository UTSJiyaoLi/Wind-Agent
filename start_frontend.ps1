param(
    [int]$Port = 8501,
    [string]$ApiBaseUrl = "http://127.0.0.1:8005"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

Write-Host "[wind-agent] Starting Streamlit UI..." -ForegroundColor Cyan
Write-Host "[wind-agent] Conda env: rag_task" -ForegroundColor Cyan
Write-Host "[wind-agent] Port: $Port" -ForegroundColor Cyan
Write-Host "[wind-agent] API Base URL: $ApiBaseUrl" -ForegroundColor Cyan

$existingFrontend = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($existingFrontend) {
    Write-Host "[wind-agent] Warning: port $Port is already in use (PID: $($existingFrontend[0].OwningProcess))." -ForegroundColor Yellow
    Write-Host "[wind-agent] Stop that process or use another port: .\\start_frontend.ps1 -Port 8502" -ForegroundColor Yellow
    exit 1
}

try {
    $apiUri = [Uri]$ApiBaseUrl
    $apiPort = $apiUri.Port
    $apiListening = Get-NetTCPConnection -State Listen -LocalPort $apiPort -ErrorAction SilentlyContinue
    if (-not $apiListening) {
        Write-Host "[wind-agent] Warning: API port $apiPort is not listening. UI can open, but data requests will fail." -ForegroundColor Yellow
        Write-Host "[wind-agent] Start backend first: conda run -n rag_task uvicorn api.app:app --host 0.0.0.0 --port $apiPort" -ForegroundColor Yellow
    }
} catch {
    Write-Host "[wind-agent] Warning: invalid API URL: $ApiBaseUrl" -ForegroundColor Yellow
}

$env:WIND_AGENT_API_BASE = $ApiBaseUrl

Write-Host "[wind-agent] Opening UI on: http://127.0.0.1:$Port" -ForegroundColor Green
Write-Host "[wind-agent] Keep this terminal open. Press Ctrl+C to stop." -ForegroundColor Green

conda run -n rag_task streamlit run ui/streamlit_app.py --server.port $Port --server.address 0.0.0.0
