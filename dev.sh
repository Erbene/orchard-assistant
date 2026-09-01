#!/usr/bin/env bash
# Start the orchard backend (FastAPI :8000) and frontend (Next :3000) together
# in this terminal.  Ctrl+C stops both.  Usage:  ./dev.sh
#
# There is no SQLite: the app always talks to the Postgres + Chroma
# containers, so this brings those up first (host-bound to 127.0.0.1).
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
py="$root/orchard-server/.venv/Scripts/python.exe"
[ -x "$py" ] || py="$root/orchard-server/.venv/bin/python"

[ -x "$py" ] || { echo "No venv. Run: cd orchard-server && python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt"; exit 1; }
[ -d "$root/orchard-web/node_modules" ] || { echo "No node_modules. Run: cd orchard-web && npm install"; exit 1; }

env_file="$root/orchard-server/.env"
env_arg=(); [ -f "$env_file" ] && env_arg=(--env-file "$env_file")

# free stale listeners on our ports
for port in 8000 3000; do
  for pid in $(netstat -ano 2>/dev/null | grep -E ":$port .*LISTEN" | awk '{print $NF}' | sort -u); do
    echo "  stopping pid $pid on :$port"; taskkill //F //PID "$pid" >/dev/null 2>&1 || kill "$pid" 2>/dev/null || true
  done
done

echo "Bringing up postgres + chromadb (docker compose)..."
docker compose -f "$root/orchard-server/docker-compose.yml" up -d --wait postgres chromadb

if [ -f "$env_file" ]; then
  ( cd "$root/orchard-server" && "$py" -c "from app.config import Settings; s=Settings(); print(f'config: rachio={s.rachio_enabled} db={s.postgres_db}@{s.postgres_host}:{s.postgres_port}')" ) 2>&1 || true
fi

pids=()
cleanup() {
  echo; echo "stopping..."
  for p in "${pids[@]}"; do
    taskkill //F //T //PID "$p" >/dev/null 2>&1 || kill "$p" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

( cd "$root/orchard-server" && "$py" -m uvicorn app.main:app --reload --port 8000 "${env_arg[@]}" ) &
pids+=($!)
( cd "$root/orchard-web" && npm run dev ) &
pids+=($!)

echo "backend  http://127.0.0.1:8000   |   frontend  http://localhost:3000   |   Ctrl+C to stop both"
wait
