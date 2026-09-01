# Start the orchard backend (FastAPI :8000) and frontend (Next :3000)
# bare-metal for fast iteration, each in its own terminal window.
#
# There is no SQLite: the app always talks to the Postgres + Chroma
# containers, so this script brings those up first (they're host-bound to
# 127.0.0.1, and Settings defaults already point at localhost).
#
#   Usage:  ./dev.ps1
$ErrorActionPreference = "Stop"
$root     = $PSScriptRoot
$backend  = Join-Path $root "orchard-server"
$frontend = Join-Path $root "orchard-web"
$py       = Join-Path $backend ".venv\Scripts\python.exe"
$compose  = Join-Path $backend "docker-compose.yml"

if (-not (Test-Path $py)) {
    throw "No venv. Run:  cd orchard-server; python -m venv .venv; .venv\Scripts\python -m pip install -r requirements.txt"
}
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    throw "No node_modules. Run:  cd orchard-web; npm install"
}

Write-Host "Bringing up postgres + chromadb (docker compose)..." -ForegroundColor Cyan
docker compose -f $compose up -d --wait postgres chromadb
if ($LASTEXITCODE -ne 0) {
    throw "docker compose failed. Is Docker Desktop running? Postgres + Chroma are required."
}

Write-Host "backend  -> http://127.0.0.1:8000   (docs: /docs, MCP: /mcp/sse)" -ForegroundColor Green
Write-Host "frontend -> http://localhost:3000" -ForegroundColor Green
Write-Host "Close each window (or Ctrl+C in it) to stop that server."
Write-Host "The postgres/chromadb containers keep running; 'docker compose -f orchard-server/docker-compose.yml down' to stop them."

Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$backend'; & '$py' -m uvicorn app.main:app --reload --port 8000"
)
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$frontend'; npm run dev"
)
