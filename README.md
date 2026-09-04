# Orchard Assistant

<p align="center">
  <img src="resources/readmethumbnail.jpg" alt="Orchard Assistant robot tending a fruit orchard with drip irrigation" width="900">
</p>

**Grounded horticulture chat, JIT labor packing, and water-saving irrigation supervision with human approval.**

Public repo: [github.com/Erbene/orchard-assistant](https://github.com/Erbene/orchard-assistant)

---

## The problem

A home grower with mixed tropical and subtropical species faces three recurring pressures:

- **Automatic irrigation can run up significant bills** when schedules ignore soil moisture, rain, and species-specific water needs.
- **Weekend labor is scarce** — pruning, fertilizing, and pest checks compete for the same few hours.
- **Horticulture advice must be grounded** in the grower's own notes and linked sources, not generic LLM guesses.

Orchard Assistant is a personal assistant for that grower: three LangGraph workflows over a real orchard inventory, knowledge base, and Rachio zones.

---

## What ships

| Workflow | UI | What it does |
| -------- | -- | ------------ |
| **Grounded chat** | `/assistant` | Routes questions to cited agronomy answers (Chroma RAG) or hands off to scheduling. Refuses unsafe or off-topic requests. |
| **JIT labor packing** | `/schedule` | Foreman negotiates available minutes and tools, escalates time-critical tasks, and packs a knapsack plan — nothing writes to the task DB until you confirm. |
| **Irrigation supervision** | `/irrigation` | Supervisor reads weather and moisture, runs a Tree-of-Thoughts zone-duration solver, and pauses before execution. Watering/pass proposals require approval; skips may be configured for auto-approval. |

Supporting surfaces: `/trees` and `/trees/[id]` (CRUD + Care Plan tab), `/sources` (knowledge-base upload and tree linking), `/zones` (live Rachio zone list).

Deep API docs, agent prompts, and eval log: **[orchard-server/README.md](orchard-server/README.md)**.

---

## Architecture

```mermaid
flowchart LR
  subgraph inputs [External inputs]
    NWS[NWS forecast]
    Rachio[Rachio zones + schedule]
    Ollama[Ollama 7B]
  end

  UI[Next.js UI<br/>orchard-web :3000]

  subgraph api [FastAPI orchard-server :8000]
    Orch[Orchestrator graph]
    Fore[Foreman graph]
    Irr[Irrigation Supervisor graph]
  end

  Chroma[(Chroma RAG)]
  PG[(Postgres + pgvector)]
  HITL{Grower approval}
  DryRun[Dry-run result]
  Zones[/zones manual water]

  UI --> api
  Ollama --> Orch & Fore & Irr
  NWS --> Irr
  Rachio --> Irr

  Orch --> Chroma
  Fore --> PG
  Irr --> PG
  Irr --> HITL --> DryRun
  Zones -->|real write; bypasses HITL| Rachio
```

**Orchestrator** — one LLM classify call per turn; agronomy path retrieves from Chroma and cites linked sources.
**Foreman** — deterministic escalation, biological-date blocks, and knapsack packing in Python; optional LLM narration.
**Irrigation Supervisor** — water-balance deficit scoring and ToT beam-search duration solver in Python; LLM writes grower-facing prose; graph pauses at HITL before any Rachio write (currently `dry_run`).

---

## Design principle

| Layer | Owns |
| ----- | ---- |
| **LLM (Ollama)** | Intent routing, cited prose, negotiation narration, plan summaries |
| **Deterministic Python** | Water balance, duration beam search, two-day irrigation gap, biological calendar dates, escalation weights, knapsack packing |
| **Grower** | Available time, tools on hand, source priority order, and irrigation approval |

---

## Quickstart (Windows)

**Prerequisites:** Docker Desktop, [Ollama](https://ollama.com) for local inference.

```powershell
cd orchard-server
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env          # review local password; Rachio and orchard coordinates are optional

cd ..\orchard-web
npm install

ollama serve
ollama pull qwen2.5:7b-instruct

cd ..
.\dev.ps1                       # bare-metal app + containerised Postgres/Chroma
.\dev.ps1 -Demo                 # optional: irrigation demo scenarios on /irrigation
```

**Full stack in Docker** (Postgres, Chroma, backend, frontend):

```powershell
docker compose -f orchard-server/docker-compose.yml up -d --build
```

**Ports** (bound to `127.0.0.1`): UI **3000**, API **8000** (`/docs`), Postgres **5433**, Chroma **8001**, Ollama **11434**.

Optional LangSmith tracing for irrigation: set `LANGCHAIN_TRACING_V2=true` and `LANGCHAIN_API_KEY` in `orchard-server/.env`.

---

## Demo walkthrough

After `.\dev.ps1 -Demo` (or `ORCHARD_DEMO=true`):

1. **`/assistant`** — Ask a species-specific care question with linked sources; confirm citations. Ask to plan weekend work; follow the schedule handoff redirect.
2. **`/schedule`** — Enter available minutes and tools; walk the Foreman interrupts; inspect the packed plan before completing.
3. **`/irrigation`** — Select **Mixed zone: mango vs. a thirsty neighbour** (`mixed-zone-tot`), click **Apply** (pins stub readings only — selecting a radio does **not** run the graph), then click **Run Supervision Task**. Inspect the HITL queue (duration change, per-species projected VWC, Approve/Reject). With LangSmith enabled, open the `irrigation.tot_solver` trace to see beam-search candidates.

Other demo presets: `rain-skip` (skip schedule after heavy QPF), `drought-emergency` (emergency run proposal).

---

## Routes & capabilities

| Route | Purpose |
| ----- | ------- |
| `/assistant` | Grounded chat (Orchestrator + Ollama SSE) |
| `/schedule` | Task inbox + Foreman JIT dialog |
| `/irrigation` | Supervisor HITL queue + schedule/settings + Run Supervision Task |
| `/trees`, `/trees/[id]` | Tree CRUD, Care Plan tab, linked sources |
| `/zones` | Rachio zones (read-only list; **manual water is a real Rachio write**) |
| `/sources` | Knowledge-base upload, compose, and tree linking |

MCP endpoint (when backend is running): `http://127.0.0.1:8000/mcp/sse`.

---

## Tests & evaluation

```powershell
cd orchard-server
.venv\Scripts\python -m pytest
.venv\Scripts\python -m eval          # needs Ollama; see orchard-server/eval/README.md
```

Eval harness details: **[orchard-server/eval/README.md](orchard-server/eval/README.md)**.

| Channel | Exact gate | Notes |
| ------- | ---------- | ----- |
| Full dataset (chat 25 + schedule 12 + irrigation 12) | **49/49** | Re-run 2026-09-03 after Care Plan v2 / two-day gap / HITL |
| Chat + schedule overlap (Sept 2 baseline set) | **36/36** | `orchard-server/eval/baselines/2026-09-02-full-7b.json` |
| Irrigation | **12/12** | Prior 11/11 plus `irr-12-two-day-gap` |

Irrigation **AI judge is parked** (~3/12 on a recent run — advisory, not a ship gate). **7B vs 14B agronomist:** no quality gain on the eval set; 14B ~20× slower on CPU — see the server README eval log.

---

## Safety & limitations

Read these before connecting a live Rachio account.

- **Supervisor Approve is `dry_run`** — proposals queue for HITL, but approved actuation does not call Rachio's live start endpoint in the current build.
- **Moisture is stubbed** — demo pins and synthetic readings; no soil-sensor hardware integration.
- **`/zones` manual watering bypasses HITL** — it performs a real Rachio write outside the supervisor queue.
- **Weather unavailable** when `ORCHARD_LAT` / `ORCHARD_LON` are unset (`available: false`).
- **Not shipped:** frost watch, camera/vision agent, CrewAI orchestration, four-tier RAG fusion.
- **Not licensed agronomic advice** — a decision-support tool for a single grower's orchard; verify critical actions independently.

---

## Repository map

```
orchard-assistant/
├── dev.ps1                 # Windows dev launcher (Postgres/Chroma + backend + frontend)
├── dev.sh                  # Linux/macOS equivalent
├── orchard-server/         # FastAPI, LangGraph agents, irrigation engine, eval harness
│   ├── app/agent/          Orchestrator, Foreman, Irrigation Supervisor graphs
│   ├── app/irrigation/     Water balance, ToT solver, phenology, weather, demo pins
│   ├── eval/               Offline scored scenarios (chat, schedule, irrigation)
│   └── docker-compose.yml  Postgres, Chroma, optional full-stack containers
└── orchard-web/            # Next.js UI (assistant, schedule, irrigation, trees, sources)
```

Local-only folders (`docs/`, `future_work/`, `capstone_submissions/`) are gitignored and not in the public repo.

---

## Design evolution

Early capstone concepts centered on frost protection for a single crop. In practice, frost is rare in this climate; **poorly tuned automatic irrigation is the recurring cost risk**. The shipped system repurposed that supervision pattern for water-saving Rachio control and added JIT labor packing for scarce weekend time.

Implementation diverged from early write-ups: **LangGraph** (not CrewAI), **Chroma + `priority_order` RAG** (not four-tier fusion), and **Tree-of-Thoughts for zone duration** (not task planning). Readers do not need prior submission context — the code and eval baselines above reflect what runs today.
