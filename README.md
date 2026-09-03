# Orchard Assistant

A home-orchard personal assistant: grounded horticulture chat, Just-In-Time (JIT) labor scheduling, and water-saving irrigation supervision over your real Rachio zones.

## Pivot

Frost is a one-in-a-century event here; a **$400 water bill** is why the shipped system is **water-saving irrigation + JIT labor**, not continuous frost watch. Capstone write-ups 1–6 were frost-first; the code diverged (LangGraph not CrewAI; Tree-of-Thoughts is zone duration, not task planning; RAG is Chroma + `priority_order`, not four-tier fusion).

## Architecture

**Next.js** (`orchard-web`) + **FastAPI** (`orchard-server`) + **Postgres/pgvector** + **Chroma** + **Ollama**; three **LangGraph** graphs (Orchestrator chat, Foreman JIT schedule, Irrigation supervisor HITL + ToT zone solver). Deterministic Python handles water balance, canopy scaling, biological calendar dates, and the 2-day irrigation gap guard.

| Route | Purpose |
| ----- | ------- |
| `/assistant` | Grounded chat (Orchestrator + Ollama) |
| `/schedule` | Task inbox + Foreman JIT dialog |
| `/irrigation` | Supervisor HITL queue + schedule/settings |
| `/trees`, `/trees/[id]` | Tree CRUD + Care Plan tab |
| `/zones` | Rachio zones (read-only list; manual water is a real Rachio write) |
| `/sources` | Knowledge-base upload and linking |

Deep API, agent prompts, and eval log: **[orchard-server/README.md](orchard-server/README.md)**.

## Setup (Windows)

**Prerequisites:** Docker Desktop; [Ollama](https://ollama.com) for local LLM inference.

```powershell
cd orchard-server
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env

cd ..\orchard-web
npm install

ollama serve
ollama pull qwen2.5:7b-instruct

cd ..
.\dev.ps1              # bare-metal app + containerised Postgres/Chroma
.\dev.ps1 -Demo        # optional: irrigation demo scenarios on /irrigation
```

**Full stack in Docker** (Postgres, Chroma, backend, frontend):

```powershell
docker compose -f orchard-server/docker-compose.yml up -d --build
```

**Ports** (all bound to `127.0.0.1`): UI **3000**, API **8000** (`/docs`), Postgres **5433**, Chroma **8001**, Ollama **11434**.

## Tests & evaluation

```powershell
cd orchard-server
.venv\Scripts\python -m pytest
.venv\Scripts\python -m eval          # needs Ollama; see orchard-server/eval/README.md
```

**Eval snapshot** (exact is the gate; AI judge is parked):

| Channel | Exact | Source |
| ------- | ----- | ------ |
| Chat + schedule (overlap with Sept 2 set) | **36/36** | `orchard-server/eval/baselines/2026-09-02-full-7b.json` |
| Full dataset (chat 25 + schedule 12 + irrigation 12) | **49/49** | re-run 2026-09-03 after Care Plan v2 / 2-day / HITL |
| Irrigation | **12/12** | prior 11/11 plus `irr-12-two-day-gap` |

Irrigation **AI judge is parked** (~3/12 this run, not a ship gate). **7B vs 14B agronomist:** no quality gain on the eval set; 14B ~20× slower — see the server README eval log.

## Limitations

- Rachio supervisor actuation is **`dry_run`**; moisture hardware is stubbed.
- Weather returns `available: false` when `ORCHARD_LAT` / `ORCHARD_LON` are unset.
- Frost watch, vision agent, CrewAI, and four-tier RAG are **not shipped**.
- `/zones` manual water bypasses the irrigation HITL queue (real Rachio write).
- `docs/` and `future_work/` are local-only (gitignored).
