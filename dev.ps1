# Start the orchard backend (FastAPI :8000) and frontend (Next :3000)
# bare-metal for fast iteration, each in its own terminal window.
#
# There is no SQLite: the app always talks to the Postgres + Chroma
# containers, so this script brings those up first (host-bound to 127.0.0.1).
# orchard-server/.env is loaded by app/config.py and uvicorn --env-file.
#
# Uvicorn lifespan starts the in-process irrigation supervisor loop
# (ORCHARD_SUPERVISOR_LOOP unset = on; 0/false/off = off) — same path as
# **Run Supervision Task**. ORCHARD_DEMO=true shows three radio scenarios on
# /irrigation (Apply pins only; grower then clicks Run). Chat needs
# `ollama serve` (this script warns but does not start Ollama).
#
#   Usage:  ./dev.ps1
#           ./dev.ps1 -Demo
param(
    [switch]$Demo
)

$ErrorActionPreference = "Stop"
$root     = $PSScriptRoot
$backend  = Join-Path $root "orchard-server"
$frontend = Join-Path $root "orchard-web"
$py       = Join-Path $backend ".venv\Scripts\python.exe"
$compose  = Join-Path $backend "docker-compose.yml"
$envFile  = Join-Path $backend ".env"
$envExample = Join-Path $backend ".env.example"
$webEnvFile = Join-Path $frontend ".env.local"
$webEnvExample = Join-Path $frontend ".env.example"

if (-not (Test-Path $py)) {
    throw "No venv. Run:  cd orchard-server; python -m venv .venv; .venv\Scripts\python -m pip install -r requirements.txt"
}
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    throw "No node_modules. Run:  cd orchard-web; npm install"
}

# --- seed .env from examples (never overwrite) -----------------------------
if (-not (Test-Path $envFile) -and (Test-Path $envExample)) {
    Copy-Item $envExample $envFile
    Write-Host "Created orchard-server/.env from .env.example — set POSTGRES_PASSWORD, RACHIO_API_KEY, NWS_USER_AGENT" -ForegroundColor Yellow
}
if (-not (Test-Path $webEnvFile) -and (Test-Path $webEnvExample)) {
    Copy-Item $webEnvExample $webEnvFile
    Write-Host "Created orchard-web/.env.local from .env.example (FASTAPI_URL)" -ForegroundColor Yellow
}

# --- stop every stale backend/frontend process (a re-run must be clean) -----
Write-Host "Stopping any running orchard dev servers..." -ForegroundColor Cyan
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='node.exe'" |
    Where-Object {
        $_.CommandLine -and (
            $_.CommandLine -match 'uvicorn' -or
            $_.CommandLine -match 'multiprocessing.*parent_pid' -or
            $_.CommandLine -match 'orchard-web.*next(\s|\\).*dev' -or
            $_.CommandLine -match 'next\\dist\\bin\\next.*dev'
        )
    } | ForEach-Object {
        Write-Host "  kill pid $($_.ProcessId)  ($($_.Name))" -ForegroundColor DarkGray
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
foreach ($port in 8000, 3000) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
            Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
        }
}
Start-Sleep -Seconds 1
$busy = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    throw "Port 8000 is still held by pid $($busy.OwningProcess) - close that window or run: Stop-Process -Id $($busy.OwningProcess) -Force"
}

Write-Host "Bringing up postgres + chromadb (docker compose)..." -ForegroundColor Cyan
docker compose -f $compose up -d --wait --wait-timeout 180 postgres chromadb
if ($LASTEXITCODE -ne 0) {
    throw "docker compose failed. Is Docker Desktop running? Postgres + Chroma are required."
}

# --- sanity: does the venv resolve config from .env? -----------------------
$checkLine = $null
$ollamaUrl = "http://localhost:11434"
$demoOn = $false
if (Test-Path $envFile) {
    Push-Location $backend
    if ($Demo) { $env:ORCHARD_DEMO = "true" }
    $pyCheck = @'
import os
from app.config import Settings
s = Settings()
tracing = os.environ.get("LANGCHAIN_TRACING_V2", "").strip().lower() in {"1", "true", "yes", "on"}
tr = "on" if tracing else "off"
sep = "@"
print(
    f"db={s.postgres_db}{sep}{s.postgres_host}:{s.postgres_port} "
    f"chroma={s.chroma_host}:{s.chroma_port} "
    f"rachio={s.rachio_enabled} demo={s.orchard_demo} "
    f"ollama={s.ollama_base_url} tracing={tr}"
)
'@
    $checkLine = & $py -c $pyCheck 2>&1 | Out-String
    $checkLine = $checkLine.Trim()
    if ($Demo) { Remove-Item Env:ORCHARD_DEMO -ErrorAction SilentlyContinue }
    Pop-Location
    Write-Host "config: $checkLine" -ForegroundColor DarkGray
    if ($checkLine -match 'ollama=(\S+)') { $ollamaUrl = $Matches[1] }
    if ($checkLine -match 'demo=True') { $demoOn = $true }
} else {
    Write-Host "note: orchard-server/.env not found — copy .env.example and set POSTGRES_PASSWORD / RACHIO_API_KEY / NWS_USER_AGENT" -ForegroundColor Yellow
}
if ($Demo) { $demoOn = $true }

try {
    Invoke-WebRequest -Uri "$ollamaUrl/api/version" -TimeoutSec 2 -UseBasicParsing | Out-Null
} catch {
    Write-Host "warning: Ollama not reachable at $ollamaUrl — chat and irrigation LLM will 503 until ``ollama serve`` + ``ollama pull qwen2.5:7b-instruct``" -ForegroundColor Yellow
}

if ($demoOn) {
    Write-Host "demo: /irrigation shows three preset scenarios — Apply, then **Run Supervision Task**; set LANGCHAIN_TRACING_V2=true + LANGCHAIN_API_KEY for irrigation.tot_solver traces in LangSmith" -ForegroundColor Cyan
}

Write-Host "backend  -> http://127.0.0.1:8000/docs" -ForegroundColor Green
Write-Host "frontend -> http://localhost:3000  (/assistant /schedule /irrigation /trees)" -ForegroundColor Green
Write-Host "MCP      -> http://127.0.0.1:8000/mcp/sse" -ForegroundColor Green
if ($demoOn) {
    Write-Host "demo     -> http://localhost:3000/irrigation  (preset scenarios)" -ForegroundColor Green
}
Write-Host "Close each window (or Ctrl+C in it) to stop that server."
Write-Host "Postgres/Chroma keep running; stop with: docker compose -f orchard-server/docker-compose.yml down"

$uvicorn = if (Test-Path $envFile) {
    "& '$py' -m uvicorn app.main:app --reload --port 8000 --env-file '$envFile'"
} else {
    "& '$py' -m uvicorn app.main:app --reload --port 8000"
}
$demoPrefix = if ($Demo) { "`$env:ORCHARD_DEMO='true'; " } else { "" }
Start-Process powershell -ArgumentList @("-NoExit", "-Command", "Set-Location '$backend'; ${demoPrefix}$uvicorn")
Start-Process powershell -ArgumentList @("-NoExit", "-Command", "Set-Location '$frontend'; npm run dev")
