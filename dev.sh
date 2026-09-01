#!/usr/bin/env bash
# Start the orchard backend (FastAPI :8000) and frontend (Next :3000) together
# in this terminal.  Ctrl+C stops both.  Usage:  ./dev.sh
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
py="$root/orchard-server/.venv/Scripts/python.exe"
[ -x "$py" ] || py="$root/orchard-server/.venv/bin/python"

[ -x "$py" ] || { echo "No venv. Run: cd orchard-server && python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt"; exit 1; }
[ -d "$root/orchard-web/node_modules" ] || { echo "No node_modules. Run: cd orchard-web && npm install"; exit 1; }

pids=()
cleanup() {
  echo; echo "stopping..."
  for p in "${pids[@]}"; do
    taskkill //F //T //PID "$p" >/dev/null 2>&1 || kill "$p" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

( cd "$root/orchard-server" && "$py" -m uvicorn app.main:app --reload --port 8000 ) &
pids+=($!)
( cd "$root/orchard-web" && npm run dev ) &
pids+=($!)

echo "backend  http://127.0.0.1:8000   |   frontend  http://localhost:3000   |   Ctrl+C to stop both"
wait
