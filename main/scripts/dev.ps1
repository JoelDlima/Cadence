# Cadence one-command dev environment (PowerShell).
# Usage:  powershell -ExecutionPolicy Bypass -File main\scripts\dev.ps1
#
# Brings up:  FastAPI on :8000, Vite dev server on :3000
# Requires:   Python 3.12+, Node 20+, pip, npm

$ErrorActionPreference = "Stop"
$ProgressPreference   = "SilentlyContinue"

$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
$MainDir  = Join-Path $RepoRoot "main"
$LogsDir  = Join-Path $MainDir "logs"
Set-Location $MainDir

# 1. venv
if (-not (Test-Path ".venv")) {
    Write-Host "==> creating venv (.venv)"
    py -3.12 -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install -q --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -q -e ".[dev]"

# 2. .env
if (-not (Test-Path ".env")) {
    Write-Host "==> creating default .env (no real keys; DEMO mode)"
    Copy-Item -Path .env.example -Destination .env -Force
}

# 3. start API
New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
New-Item -ItemType Directory -Force -Path data | Out-Null
Write-Host "==> starting FastAPI on http://127.0.0.1:8000"
$ApiProcess = Start-Process -FilePath .\.venv\Scripts\python.exe `
    -ArgumentList @("-m","uvicorn","revive.api.app:app","--port","8000","--host","127.0.0.1") `
    -WorkingDirectory $MainDir `
    -RedirectStandardOutput (Join-Path $LogsDir "api.log") `
    -RedirectStandardError  (Join-Path $LogsDir "api.err") `
    -PassThru
Write-Host "    API PID: $($ApiProcess.Id)  (log: $LogsDir\api.log)"

# 4. wait for API
$ready = $false
for ($i=1; $i -le 30; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/metrics" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch {}
    Start-Sleep -Milliseconds 500
}
if ($ready) { Write-Host "    API ready" } else { Write-Host "    API NOT ready (check logs/api.err)" -ForegroundColor Yellow }

# 5. start web
Set-Location (Join-Path $MainDir "frontend")
if (-not (Test-Path "node_modules")) {
    Write-Host "==> installing frontend deps (this can take a minute)"
    npm install
}
Write-Host "==> starting Vite on http://127.0.0.1:3000"
$WebProcess = Start-Process -FilePath npm.cmd `
    -ArgumentList @("run","dev","--","--host","127.0.0.1","--port","3000") `
    -WorkingDirectory (Join-Path $MainDir "frontend") `
    -RedirectStandardOutput (Join-Path $LogsDir "web.log") `
    -RedirectStandardError  (Join-Path $LogsDir "web.err") `
    -PassThru
Write-Host "    Web PID: $($WebProcess.Id)  (log: $LogsDir\web.log)"

Write-Host @"

================================================================
 Revive is up.

   API : http://127.0.0.1:8000/console
   Web : http://127.0.0.1:3000
   API logs : $LogsDir\api.log
   Web logs : $LogsDir\web.log

   Cadence is running in DEMO mode (no Razorpay keys needed).
   Add keys to main/.env to switch to LIVE mode.

 Try a synthetic failure:

   Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/test/inject `
        -ContentType 'application/json' `
        -Body '{"subscription_id":"sub_demo","customer_id":"cust_demo",
                "failure_code":"insufficient_funds","amount_minor":49900,
                "error_description":"Simulated from dev.ps1"}'

 Press Ctrl+C to stop.
================================================================
"@

# Keep window open until the user closes it
Write-Host "Press any key to stop both services..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
Write-Host "==> stopping"
Stop-Process -Id $ApiProcess.Id -ErrorAction SilentlyContinue
Stop-Process -Id $WebProcess.Id -ErrorAction SilentlyContinue
Get-Process -Name "uvicorn","node" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
