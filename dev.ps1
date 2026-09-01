# Start the orchard backend (FastAPI :8000) and frontend (Next :3000)
# bare-metal for fast iteration, each in its own terminal window.
#
# There is no SQLite: the app always talks to the Postgres + Chroma
# containers, so this script brings those up first (host-bound to 127.0.0.1).
# orchard-server/.env is loaded for both (uvicorn --env-file + app/config.py).
#
#   Usage:  ./dev.ps1
$ErrorActionPreference = "Stop"
$root     = $PSScriptRoot
$backend  = Join-Path $root "orchard-server"
$frontend = Join-Path $root "orchard-web"
$py       = Join-Path $backend ".venv\Scripts\python.exe"
$compose  = Join-Path $backend "docker-compose.yml"
$envFile  = Join-Path $backend ".env"

if (-not (Test-Path $py)) {
    throw "No venv. Run:  cd orchard-server; python -m venv .venv; .venv\Scripts\python -m pip install -r requirements.txt"
}
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    throw "No node_modules. Run:  cd orchard-web; npm install"
}

# --- stop every stale backend/frontend process (a re-run must be clean) -----
Write-Host "Stopping any running orchard dev servers..." -ForegroundColor Cyan
# by command line: uvicorn workers + reload children + next dev
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='node.exe'" |
    Where-Object {
        $_.CommandLine -and (
            $_.CommandLine -match 'uvicorn\s+app\.main' -or
            $_.CommandLine -match 'multiprocessing.*parent_pid' -or
            $_.CommandLine -match 'orchard-web.*next(\s|\\).*dev' -or
            $_.CommandLine -match 'next\\dist\\bin\\next.*dev'
        )
    } | ForEach-Object {
        Write-Host "  kill pid $($_.ProcessId)  ($($_.Name))" -ForegroundColor DarkGray
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
# by port, as a backstop
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
docker compose -f $compose up -d --wait postgres chromadb
if ($LASTEXITCODE -ne 0) {
    throw "docker compose failed. Is Docker Desktop running? Postgres + Chroma are required."
}

# --- sanity: does the venv resolve config from .env? -----------------------
if (Test-Path $envFile) {
    Push-Location $backend
    $check = & $py -c "from app.config import Settings; s=Settings(); print(f'rachio={s.rachio_enabled} db={s.postgres_db}@{s.postgres_host}:{s.postgres_port}')" 2>&1
    Pop-Location
    Write-Host "config: $check" -ForegroundColor DarkGray
} else {
    Write-Host "note: orchard-server/.env not found - copy .env.example and set POSTGRES_PASSWORD / RACHIO_API_KEY" -ForegroundColor Yellow
}

Write-Host "backend  -> http://127.0.0.1:8000   (docs: /docs, MCP: /mcp/sse)" -ForegroundColor Green
Write-Host "frontend -> http://localhost:3000" -ForegroundColor Green
Write-Host "Close each window (or Ctrl+C in it) to stop that server."
Write-Host "Postgres/Chroma keep running; stop with: docker compose -f orchard-server/docker-compose.yml down"

$uvicorn = if (Test-Path $envFile) {
    "& '$py' -m uvicorn app.main:app --reload --port 8000 --env-file '$envFile'"
} else {
    "& '$py' -m uvicorn app.main:app --reload --port 8000"
}
Start-Process powershell -ArgumentList @("-NoExit", "-Command", "Set-Location '$backend'; $uvicorn")
Start-Process powershell -ArgumentList @("-NoExit", "-Command", "Set-Location '$frontend'; npm run dev")
