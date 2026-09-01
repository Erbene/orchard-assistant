# Start the orchard backend (FastAPI :8000) and frontend (Next :3000),
# each in its own terminal window.  Usage:  ./dev.ps1
$ErrorActionPreference = "Stop"
$root     = $PSScriptRoot
$backend  = Join-Path $root "orchard-server"
$frontend = Join-Path $root "orchard-web"
$py       = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    throw "No venv. Run:  cd orchard-server; python -m venv .venv; .venv\Scripts\python -m pip install -r requirements.txt"
}
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    throw "No node_modules. Run:  cd orchard-web; npm install"
}

Write-Host "backend  -> http://127.0.0.1:8000   (docs: /docs, MCP: /mcp/sse)" -ForegroundColor Green
Write-Host "frontend -> http://localhost:3000" -ForegroundColor Green
Write-Host "Close each window (or Ctrl+C in it) to stop that server."

Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$backend'; & '$py' -m uvicorn app.main:app --reload --port 8000"
)
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$frontend'; npm run dev"
)
