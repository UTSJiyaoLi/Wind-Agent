param(
    [switch]$SkipNpmInstall
)

$ErrorActionPreference = "Stop"

function Write-Info([string]$msg) {
    Write-Host "[INFO] $msg" -ForegroundColor Cyan
}

function Write-Warn([string]$msg) {
    Write-Host "[WARN] $msg" -ForegroundColor Yellow
}

function Write-Ok([string]$msg) {
    Write-Host "[OK] $msg" -ForegroundColor Green
}

function Ensure-NodeAndNpm {
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($npm) {
        Write-Ok "npm found: $($npm.Source)"
        return
    }

    Write-Warn "npm not found. Trying to install Node.js LTS via winget..."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Neither npm nor winget is available. Install Node.js LTS manually, then rerun this script."
    }

    winget install --id OpenJS.NodeJS.LTS -e --source winget --accept-package-agreements --accept-source-agreements | Out-Host
    Start-Sleep -Seconds 2

    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npm) {
        throw "Node.js installation finished but npm.cmd is still unavailable in PATH. Open a new terminal and rerun."
    }

    Write-Ok "Node.js LTS installed and npm is available."
}

function Ensure-SshClient {
    $ssh = Get-Command ssh -ErrorAction SilentlyContinue
    $plink = Get-Command plink.exe -ErrorAction SilentlyContinue
    if ($ssh -or $plink) {
        if ($ssh) { Write-Ok "ssh found: $($ssh.Source)" }
        if ($plink) { Write-Ok "plink found: $($plink.Source)" }
        return
    }

    Write-Warn "No ssh/plink found. Trying to enable Windows OpenSSH Client..."
    try {
        Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0 -ErrorAction Stop | Out-Host
    } catch {
        Write-Warn "Auto-enable OpenSSH failed: $($_.Exception.Message)"
    }

    $ssh = Get-Command ssh -ErrorAction SilentlyContinue
    if ($ssh) {
        Write-Ok "ssh found after enabling OpenSSH: $($ssh.Source)"
        return
    }

    Write-Warn "OpenSSH still unavailable. Trying to install PuTTY (plink) via winget..."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        winget install --id PuTTY.PuTTY -e --source winget --accept-package-agreements --accept-source-agreements | Out-Host
    } else {
        Write-Warn "winget not found. Cannot auto-install PuTTY."
    }

    $plink = Get-Command plink.exe -ErrorAction SilentlyContinue
    if ($plink) {
        Write-Ok "plink found: $($plink.Source)"
        return
    }

    throw "No ssh client is available. Install OpenSSH client or PuTTY, then rerun."
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..\\..")).Path
$webDir = Join-Path $repoRoot "apps\\web"

Write-Info "Repo root: $repoRoot"

if (-not (Test-Path (Join-Path $webDir "package.json"))) {
    throw "Missing frontend project: $webDir\\package.json"
}

Ensure-NodeAndNpm
Ensure-SshClient

if (-not $SkipNpmInstall) {
    Write-Info "Installing frontend dependencies in apps/web ..."
    Push-Location $webDir
    try {
        if (Test-Path "package-lock.json") {
            npm ci | Out-Host
        } else {
            npm install | Out-Host
        }
    } finally {
        Pop-Location
    }
    Write-Ok "Frontend dependencies are installed."
} else {
    Write-Warn "SkipNpmInstall is set. Frontend dependency installation was skipped."
}

Write-Host ""
Write-Ok "Minimal local environment is ready."
Write-Host "Next: run .\\wind_agent_chatui.cmd" -ForegroundColor Green
