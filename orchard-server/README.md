# Orchard Assistant API

FastAPI service for orchard **trees**, **tasks** and a **knowledge base**,
built as a clean layered architecture. No ORM — DDL lives in
`docker/postgres/init.sql`, repositories issue raw SQL (`sqlalchemy.text`)
over an async **PostgreSQL + pgvector** connection and return `dict` rows, and
"models" are the Pydantic schemas in `schemas/`. The vector store is a
**ChromaDB HTTP server**. Both run as containers (`docker-compose.yml`) —
there is no SQLite / embedded mode.

**Irrigation zones are not stored here.** They are the grower's real
**Rachio** zones, read live and **read-only** through the Rachio Public API
([app/services/rachio.py](app/services/rachio.py)) — all zone configuration is
edited in the official Rachio app. The one write we perform is starting a
manual watering run. `tree.zone_id` is just a free-text reference to a Rachio
zone id.

## Layers

```
app/
  main.py            composition root: app, routers, exception handlers, lifespan
  config.py          Settings (env-driven, framework-free)
  core/db.py         async SQLAlchemy engine cache + connection ctx manager
  core/vector_db.py  Chroma HTTP client (no auth)
  dependencies.py    FastAPI Depends() wiring: connection -> repo -> service
  mcp_server.py      FastMCP server: service logic as MCP tools + resource (SSE + stdio)
  rag/               chunking, file text extraction, ChromaDB wrapper
  agent/             LangGraph agents: Orchestrator (chat router) + Foreman (scheduler)
docker/postgres/init.sql   the schema (extensions + DDL), run on first container boot
scripts/ensure_stack.py    `docker compose up --wait` the data-layer containers

  api/               HTTP LAYER - request/response, status codes, delegation only
    routes/          zones trees sources schedule chat conversations care_plan tasks

  schemas/           Pydantic transport models (free-text str, no enums)
    zone tree task source schedule chat conversation care_plan

  services/          BUSINESS LOGIC - HTTP-agnostic, returns Pydantic/plain objects
    rachio tree_service task_service source_service chat_service
    conversation_service care_plan_service foreman_service validators exceptions

  repositories/      PERSISTENCE - raw SQL only, dict rows in/out (no zone repo - Rachio)
    tree_repository task_repository task_template_repository source_repository conversation_repository
```

**Dependency flow (per request):**
`get_settings_dep -> get_connection -> get_*_repository + get_validation_agent -> get_*_service -> route handler`
(zone routes bypass the DB: `get_settings_dep -> get_rachio_service_dep`)

FastAPI caches sub-dependencies per request, so one `AsyncConnection` is
shared by every repository in a request and the request behaves as a single
transaction (commit on success, rollback on exception).

## Free text, no enums

Descriptive fields (`species`, `variety`) are plain `str` and are **stored
exactly as typed** - no enums, no closed vocabularies, never rejected for
being "unrecognized". Before a write, the **service** still awaits the
**validation agent** hook
([app/services/validators.py](app/services/validators.py)):

```python
outcome = await self._validator.validate("species", "  Mango ")
# -> ValidationOutcome(canonical="Mango", is_valid=True)   # whitespace trimmed only
```

- `PassthroughValidationAgent` (default): collapses whitespace, accepts
  everything.
- `LLMValidationAgent`: placeholder showing where a local model / MCP tool
  call goes (for *enrichment*, not gatekeeping), with graceful fallback to
  passthrough.

Swap implementations in `get_default_validation_agent()` - no service changes.
`tree.zone_id` is a free-text Rachio zone id - never validated.

## MCP / agent reuse

Service methods take and return Pydantic models or plain values and raise
framework-neutral `DomainError`s. A future MCP server can call
`TreeService.create_tree(TreeCreate(...))` directly and map `DomainError` to
tool errors, with zero HTTP coupling.

## Endpoints

All API routes are mounted under **`/api/v1`** (`GET /health` is not). The
`orchard-web` frontend proxies `/api/v1/*` straight through.

| Method | Path | Notes |
| ------ | ---- | ----- |
| `GET`    | `/api/v1/zones` | Rachio zones grouped by device (read-only); `503` if `RACHIO_API_KEY` unset |
| `GET`    | `/api/v1/zones/{zone_id}` | one Rachio zone's config; `404` if unknown |
| `POST`   | `/api/v1/zones/{zone_id}/water` | `{ duration_minutes }` → start a manual run; `202`. **No** create/update/delete — zone config is Rachio-app-only |
| `GET`    | `/api/v1/trees` | list; accepts `?species=` / `?zone_id=` (zone_id is free text) |
| `GET`    | `/api/v1/trees/{id}` | 404 if missing |
| `POST`   | `/api/v1/trees` | 201; `tree_id` auto-assigned |
| `PATCH`  | `/api/v1/trees/{id}` | partial; only supplied fields change |
| `DELETE` | `/api/v1/trees/{id}` | 204 |
| `GET/POST` | `/api/v1/sources` | KB sources; `POST` is `multipart/form-data` (`name` + `text` OR `file`) |
| `GET` | `/api/v1/sources/{id}` | includes `raw_content` |
| `PATCH/DELETE` | `/api/v1/sources/{id}` | rename (`{name}`) / delete (also purges Chroma chunks) |
| `GET/PUT` | `/api/v1/trees/{id}/sources` | list / replace the sources linked to a tree |

Tree `age_days` / `age_years` are derived from `planted_date` on read, never stored.

### Tasks (JIT scheduling model)

`task` (FK → `tree`, `ON DELETE CASCADE`), reached through the MCP tools and
the Foreman's `/api/v1/schedule/*` routes. `user_context` was **dropped** —
scheduling constraints (available minutes, resources) are gathered *just in
time* by the Foreman, not stored.

- `task`: `id`, `tree_id`, **`template_id`** (FK → `task_templates`, `ON DELETE
  SET NULL`), `action_type` (free text), `status`
  (`pending`/`completed`/`deferred`/`skipped` — a real state field, so it *is*
  constrained), `priority_score` (float), `scheduled_date` (ISO datetime, nullable),
  `frequency_days` (int, nullable), **`estimated_minutes`** (int, nullable),
  **`required_resources`** (JSON list of free-text names), `created_at`,
  `completed_at`.
- `TaskService`: `create_task` (FK-checked), `mark_complete` / `skip_task`
  (both close the task then spawn the template's next occurrence — or, for a
  template-less task, honour `frequency_days`), `defer_task`,
  `batch_update_priorities` (atomic), `create_baseline_tasks(tree_id, items)`.
- `TaskRepository.list_pending(scheduled_before=…)` — pending only, `priority_score`
  DESC; `.inbox()` — pending tasks joined to their template + tree for the
  `/api/v1/tasks` list.

### Care Plan & task generation

Per-tree routine maintenance. **`task_templates`** (`tree_id` CASCADE, `name`,
`category`, `rate_class`, `interval_days`, `estimated_minutes`, `priority_score`,
`required_resources` list[str], `resource_plan` list[{name,quantity,unit}],
`baseline_question?`, `anchor_date?`, `source_ids`). `tree` gained `height_m` /
`canopy_spread_m`.

- **[app/agent/care_plan.py](app/agent/care_plan.py)** — the *deterministic*
  size-scaler. `canopy_volume_m3(height, spread)` (half-ellipsoid; spread ≈
  0.6·height when unknown) feeds a `_RATES` table (`base_minutes` +
  `minutes_per_m³`, consumables per m³, a `Pole saw` past 3 m). The LLM never
  does the arithmetic — see the eval decision log.
- **`agronomist.generate_care_plan(tree, …)`** — `AGENT_MODEL` (7B) picks 4–9
  `_PlanItem`s (`name`, `category` enum, `rate_class`, `interval_days`,
  `priority_score`, optional `baseline_question`); Python scales each to a
  template row. Raises `LLMUnavailable` → **503** when Ollama is down.
- **`CarePlanService`** — `generate` (replace templates, drop their *pending*
  tasks), `update_template` (re-scale on `category`/`rate_class` change, resync
  the one open task), `delete_template`, `apply_baseline` (answers → per-template
  `anchor_date` → materialise the first task, `anchor + interval_days`).
- **Recurrence = one open task per template.** `mark_complete`/`skip_task`
  spawns the next (`prev.scheduled_date + interval_days`).

| Method | Path | Notes |
| ------ | ---- | ----- |
| `GET`    | `/api/v1/trees/{id}/care-plan` | templates + baseline questions + counts |
| `POST`   | `/api/v1/trees/{id}/care-plan/generate` | run the Agronomist, replace the plan (503 without Ollama) |
| `POST`   | `/api/v1/trees/{id}/care-plan/baseline` | `{answers:[{template_id,last_done}]}` → first tasks |
| `PATCH`/`DELETE` | `/api/v1/care-plan/templates/{id}` | edit / remove a template (+ its open task) |
| `GET` | `/api/v1/tasks` | the schedule inbox — pending, priority-then-date, with plan/tree labels |
| `POST` | `/api/v1/tasks/{id}/complete` · `/skip` · `/defer` | close out a task |

`orchard-web`: `/trees/[id]` has a **Care Plan tab** ("Generate Care Plan" +
auto-run on a new tree, editable templates, canopy dimensions) + a **baseline
wizard** (dynamic date form); the `/trees` list has a per-row Care Plan button
(`GET /trees` returns `has_care_plan`). `/schedule` is the **task inbox**;
"Plan a work session" opens the Foreman JIT wizard in a dialog.

### Irrigation workflow — Phase 1 ([app/irrigation/](app/irrigation/))

The water-saving deliberation engine. **Services only — no HTTP routes yet**
(the CRON triggers land in Phase 3). Phase 1 = data plumbing; Phase 2 = the
Supervisor that intercepts the baseline Rachio schedule.

- `tree` gained `estimated_gph` (total drip delivery, gal/hour).
- **`moisture_sensor`** (`id` PK, `label`, nullable `tree_id` FK + `zone_id`) —
  a probe maps to a tree, a Rachio zone, or both. `MoistureSensorService.tree_moisture(tree_id)`
  resolves a tree's effective VWC: its own sensors' mean, else its zone's, else `none`.
- **`app/irrigation/hardware.py`** — stub reads: `get_moisture(sensor_id)`
  (deterministic-per-id VWC % with seasonal drift), `get_rain_bucket_24h()`
  (mm). `set_moisture` / `set_rain_bucket_24h` / `reset` override registry for
  tests + the Phase 2 harness.
- **`app/irrigation/weather.py`** — real **NWS** (`api.weather.gov`, no key,
  needs `NWS_USER_AGENT`): `forecast(settings)` → ~7 days of quantitative
  precip (mm), PoP, temps from the **gridpoint** product; `observed_rain_mm(settings, day)`
  → nearest-station 24h observed total. `ORCHARD_LAT`/`ORCHARD_LON` unset →
  `{"available": false}` (non-fatal). `/points` cached forever, forecast ~1 h.
- **`rainfall_forecast_log`** (one row per `for_date`) + `RainfallForecastService`:
  `roll(today)` writes the 1/3/5-day-ahead QPF for `today+{1,3,5}` and backfills
  yesterday's actuals (`actual_nws_mm` observed + `actual_gauge_mm` from the
  bucket stub); `accuracy(since)` → MAE / bias / rain-hit-rate per horizon.

**Phase 2 — the Supervisor** (still services only, no routes):

- **[app/services/water_balance.py](app/services/water_balance.py)** — the
  *deterministic* sensor-fusion pre-processing. Per tree:
  `deficit_score = (target_vwc − current_vwc) − rain_24h_mm − forecast_rain_24h_mm`
  (higher = drier). `target_vwc` is **growth-stage aware**
  ([app/irrigation/phenology.py](app/irrigation/phenology.py) — a coarse
  month→stage map, stopgap for the parked biological-calendar brief).
  `for_zone` aggregates to `max` deficit (protect the driest tree). The LLM
  never does the arithmetic.
- **[app/tools/irrigation.py](app/tools/irrigation.py)** — the three actions,
  **stubbed** (log + `print`, `dry_run=True`): `rachio_skip_schedule(zone, days)`,
  `pass_no_action(zone)`, `start_zone_watering(zone, minutes)`. Also registered
  on the MCP server.
- **[app/agent/irrigation_supervisor.py](app/agent/irrigation_supervisor.py)** —
  a LangGraph node (`START → deliberate → execute → END`, async, no checkpointer).
  `deliberate` = `AGENT_MODEL` `.with_structured_output` picking one action from
  the deficit score + per-tree stages (prompt = "agronomic safety net, objective
  SAVE WATER; the baseline controller is blind to soil moisture"); `execute`
  dispatches the tool. LLM down → `pass_no_action` (defer to baseline — a CRON
  job must not crash). `IrrigationSupervisorService.run_daily()` is the CRON
  entrypoint (Phase 3 wires the trigger); `run_for_zone(zone)` for one zone.

**Schema:** all DDL is in [docker/postgres/init.sql](docker/postgres/init.sql),
applied once when the `postgres` container's volume is first created (and by
`tests/conftest.py` against the disposable `orchard_test` database). Additive
columns are also re-applied idempotently on app startup (`db.apply_startup_ddl`,
the `_STARTUP_DDL` list). A structural change still needs `docker compose
down -v` and back up.

### Knowledge base (Consensus Fusion RAG)

`sources` (`id`, `name`, `source_type` `file`|`text`, `file_path`,
`raw_content`, `upload_date`) + `tree_sources` (`tree_id`, `source_id`) mapping.
`POST /api/v1/sources` extracts text (PDF via `pypdf`, MD/TXT decoded), chunks
it (`app/rag/chunking.py`), and adds every chunk to one ChromaDB collection
with `metadata = {"source_id": <id>}`. **`search_knowledge(query, tree_id=None)`**
(MCP) retrieves and groups the results per source under
`--- SOURCE {id}: {name} ---` headers so the model does the fusion itself.
`tree_id` omitted → searches the whole KB (the common "according to my sources"
case); `tree_id` given → only that tree's linked sources. Also exposes an
`ask_sources` MCP **prompt**. Chroma persists at `ORCHARD_CHROMA_PATH` (default
`./chroma`); uploaded files at `ORCHARD_UPLOADS_DIR`. First ingest downloads the
MiniLM embedding model (~80 MB).

### Orchestrator — conversational router (`app/agent/`)

[app/agent/orchestrator.py](app/agent/orchestrator.py) is one local-LLM call
(`AGENT_MODEL`, default `qwen2.5:7b-instruct`, `.with_structured_output`) that
classifies each chat turn into one of five routes; [graph.py](app/agent/graph.py)
(async `StateGraph`, no checkpointer — `ChatService` loads the thread from
Postgres and passes the whole history in) dispatches it:

| Route | Handler | Effect |
| ----- | ------- | ------ |
| `agronomy` | `agronomist.run_agronomist` | KB retrieval → a **second** LLM call → cited answer (the only 2-call turn); general knowledge is folded in as the lowest-priority source, not forbidden |
| `schedule` | `schedule_handoff` | short reply + a `redirect` event to `/schedule` — the interrupt negotiation never happens in chat |
| `complete` | `TaskService.mark_many_complete` | marks the named tasks done, emits a `tool` event |
| `refuse` | reply only | unsafe agronomy (off-label rates, toxic mixes) or out-of-scope (weather, chit-chat, coding) |
| `smalltalk` | reply only | greeting / "what can you do" |

`agronomist.py` owns the Consensus-Fusion prompt + `format_priority_context`.
Linked sources are rendered under `[PRIORITY n SOURCE: …]` headers in the
grower's authority order; `run_agronomist` then appends one more block —
`[PRIORITY n+1 SOURCE: General horticultural knowledge (…lowest authority)]` —
so the model's own knowledge fills gaps the notes leave but **never overrides a
linked source**. The `search_knowledge` MCP tool renders retrieval only (no
general-knowledge block). The tool surface from chat is **router +
`mark_tasks_complete` only** — no CRUD.
**Ollama is required**: `/api/v1/chat` returns **503** when it is unreachable
(routing cannot be templated). The interactive scheduler is the Foreman ↓.

**Tracing.** Set `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY` and every
`ChatOllama` call and LangGraph run streams to LangSmith. `app/core/tracing.py`
adds named spans for the steps LangChain doesn't auto-instrument —
`kb.search` (the Chroma retrieval, `run_type="retriever"`), `agronomist.answer`,
`agronomist.care_plan`, `orchestrator.classify` — so an agronomy trace reads
`agronomist.answer › [kb.search, ChatOllama]` instead of two disconnected LLM
calls. Wiring / secret args (`settings`, `sources`, the DB connection) are
stripped from logged inputs. Tests force tracing off (`conftest.py`).

### Foreman — interactive JIT scheduling (Phase 4)

[app/agent/foreman.py](app/agent/foreman.py) is a **checkpointed two-interrupt
LangGraph negotiation** driven over REST:

```
time_check --(interrupt: available_minutes)--> propose --> resource_check
  --(interrupt: have_resources)--> finalize --> narrate --> END
```

- **Deterministic engine** (`escalate` / `pack` / `resources_for` / `refit`):
  [app/agent/escalation.py](app/agent/escalation.py) inflates the
  `priority_score` of dangerously-overdue tasks (keyword rules table +
  generic >14-day fallback), then a greedy knapsack packs the budget, the
  union of `required_resources` is asked about, and tasks needing a missing
  tool are dropped + the freed time backfilled. **No node writes the DB.**
- **Narration**: a local **Ollama** model (`FOREMAN_MODEL`, default
  `qwen2.5:14b`) writes the session summary. Optional — falls back to a
  template when Ollama is unreachable (`ollama serve && ollama pull qwen2.5:14b`).
- **Sessions** persist to Postgres (`langgraph-checkpoint-postgres`,
  `checkpoints*` tables) keyed by `thread_id`, resumable after a restart. The
  graph is *synchronous* (async psycopg can't run on Windows' Proactor loop)
  and `ForemanService` runs it via `asyncio.to_thread`.

| Method | Path | Notes |
| ------ | ---- | ----- |
| `POST` | `/api/v1/schedule/plan` | `{available_minutes?}` → `ScheduleState` (`step: need_time \| need_resources \| done`) + a `thread_id` |
| `POST` | `/api/v1/schedule/resume` | `{thread_id, available_minutes? \| have_resources?}` → next `ScheduleState` |
| `POST` | `/api/v1/schedule/complete` | `{task_ids}` → mark done (the UI button) |
| `POST` | `/api/v1/schedule/report` | `{text}` — "finished task 2 and 3" → marks them (regex extraction) |

DB writes happen **only** on `/complete`, `/report`, or the MCP tool
`mark_tasks_complete(task_ids)` — the schedule itself is a proposal.
`orchard-web` `/schedule` is the 3-step wizard for this flow.

### Chat (SSE) + conversation history

`POST /api/v1/chat` takes `{ "conversation_id"?: int, "message": str }` and
streams the Orchestrator turn as Server-Sent Events. **History is
server-owned**: omit `conversation_id` on the first turn — a `conversation`
row is created and its id comes back in the stream. The server loads prior
turns from Postgres, runs the graph over the whole thread, then appends the
user message + the answer.

```
data: {"type":"start"}
data: {"type":"conversation","id":7,"title":"why are my leaves yellow","new":true}
data: {"type":"tool","toolName":"mark_tasks_complete","args":{"task_ids":[3,5]},"result":[3,5]}
data: {"type":"text-delta","delta":"Marked "}
data: {"type":"redirect","href":"/schedule","label":"Open the scheduler"}
data: {"type":"finish","finishReason":"ok"}
```

[chat_service.py](app/services/chat_service.py) runs the graph and yields these
dicts; the route wraps each as an SSE frame and prepends a preflight
`GET {OLLAMA_BASE_URL}/api/version` — on failure the endpoint returns **503**
*before* the stream opens. The service opens its **own** DB connection for the
turn (a request-scoped `Depends` connection is torn down before a
`StreamingResponse` body drains).

`conversation` / `chat_message` tables (`docker/postgres/init.sql`); the graph
stays stateless. History CRUD:

| Method | Path | Notes |
| ------ | ---- | ----- |
| `GET`    | `/api/v1/conversations` | list, most-recently-updated first |
| `GET`    | `/api/v1/conversations/{id}` | the thread + every message (`meta` carries route / tool_calls / redirect) |
| `PATCH`  | `/api/v1/conversations/{id}` | `{title}` — rename |
| `DELETE` | `/api/v1/conversations/{id}` | 204; messages cascade |

`orchard-web` `/assistant` has a conversation rail (new chat / switch / delete)
and renders the deltas, the completed-tool chip, and the "Open the scheduler"
button.

## MCP server

[app/mcp_server.py](app/mcp_server.py) exposes the `TreeService` /
`TaskService` / `SourceService` / `RachioService` logic as MCP tools + a
resource, for AI-agent clients. DB-backed tools reuse the service layer
directly (one short-lived Postgres connection per call from the same pooled
engine the HTTP API uses, wrapped in a transaction) — no HTTP calls to self.

**Tools:**
- zones (Rachio, read-only) — `list_zones`, `get_zone_details`,
  **`trigger_rachio_watering(zone_id, duration_minutes)`** (the Foreman's JIT
  irrigation action; the only Rachio write). No create/update/delete.
- trees — `list_trees`, `get_tree_details`, `create_tree`, `update_tree`, `delete_tree`
- tasks (Foreman) — `get_pending_tasks`, `get_task_details`, `create_task`,
  `create_baseline_tasks`, `batch_update_task_priorities`, `mark_task_complete`,
  **`mark_tasks_complete(task_ids)`** (bulk - for "done with 3 and 5"), `defer_task`
  (`create_task` / `create_baseline_tasks` require the LLM to supply
  `estimated_minutes` + `required_resources`)
- knowledge base — `list_sources`, `add_text_source(name, text)`,
  `link_tree_sources(tree_id, source_ids)`,
  **`search_knowledge(query, tree_id=None)`** — retrieve grounded passages
  (whole KB by default, or one tree's linked sources)

**Prompt:** `ask_sources(question)` — canned "answer strictly from my ingested sources".
**Resource:** `orchard://system-summary` — tree/task/source counts, whether
Rachio is configured, + status.

Domain errors (`NotFoundError`, `DomainValidationError`, …) are re-raised as
`ToolError`, so the client sees a clean message, not a stack trace.

Two transports:

| Transport | How | Client URL |
| --------- | --- | ---------- |
| **SSE** | mounted on the FastAPI app (`app.mount("/mcp", mcp.sse_app())`) | `http://127.0.0.1:8000/mcp/sse` |
| **stdio** | `python -m app.mcp_server` | — (Claude Desktop / Cursor) |

For Claude Desktop, drop [claude_desktop_config.json](claude_desktop_config.json)
into `%APPDATA%\Claude\claude_desktop_config.json` (merge the `mcpServers` key)
and restart the app.

## Running

Everything talks to the **`postgres`** and **`chromadb`** containers in
[docker-compose.yml](docker-compose.yml) — hardened on an isolated
`orchard-net` bridge, every port bound to `127.0.0.1`, 4 GB memory caps,
health checks, Postgres tuned for a 64 GB host, no app-layer auth (Postgres
still enforces its password). There is no SQLite fallback.

Host ports: **Postgres `5433`** (container 5432 — 5432 is left for a native
install), **Chroma `8001`** (container 8000 — 8000 is the bare-metal uvicorn),
backend `8000`, frontend `3000`. `Settings` defaults and `.env.example` match.

```sh
cd orchard-server
cp .env.example .env        # set POSTGRES_PASSWORD; optionally RACHIO_API_KEY
```

`RACHIO_API_KEY` (from app.rach.io → Account) is **optional** — without it the
`/api/v1/zones` endpoints and the `list_zones` / `trigger_rachio_watering` MCP
tools return `503` / a tool error and everything else works normally.
`app/config.py` loads `orchard-server/.env` on bare-metal runs (uvicorn, `python
-m app.mcp_server`, `dev.ps1`); `docker compose` reads the same file for
`${RACHIO_API_KEY}`. Real env vars always win over `.env`.

**Local LLM (Ollama).** `/api/v1/chat` is **503** without a reachable Ollama.

| env | role | default | required? |
| --- | --- | --- | --- |
| `AGENT_MODEL` | router / classifier (short structured output) | `qwen2.5:7b-instruct` | **yes** |
| `AGRONOMIST_MODEL` | grounded Q&A over retrieved notes | *falls back to `AGENT_MODEL`* | no |
| `FOREMAN_MODEL` | JIT session summary | `qwen2.5:14b` | no — templated fallback |

`OLLAMA_BASE_URL` defaults to `http://localhost:11434` (bare-metal) /
`http://host.docker.internal:11434` (compose). Boot logs `ollama.models.missing`
if a configured model isn't pulled.

```sh
ollama serve
ollama pull qwen2.5:7b-instruct     # required for chat
ollama pull qwen2.5:14b             # optional: Foreman narration, or a stronger AGRONOMIST_MODEL
```

Why each model was chosen — with the eval numbers behind it, and when to
revisit — is logged under **[Model & prompt decisions](#model--prompt-decisions--eval-findings)** below.

**Full stack in Docker** — Postgres, Chroma, backend, frontend:

```sh
docker compose up -d --build
docker compose ps           # wait for all four "healthy"
#   backend  -> http://127.0.0.1:8000/docs
#   frontend -> http://127.0.0.1:3000
```

**Bare-metal app, containerised data** (fast iteration):

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
../dev.ps1          # brings up postgres + chromadb, then uvicorn --reload + npm run dev
```

- [docker/postgres/init.sql](docker/postgres/init.sql) — `CREATE EXTENSION vector`
  + the DDL (identity PKs, `TIMESTAMPTZ`, `JSONB`, plus a `source_chunks`
  table with a `vector(384)` HNSW index). Runs once, on first container boot.
- [app/core/db.py](app/core/db.py) — async SQLAlchemy engine cache +
  `connection(settings)` context manager (the per-request unit of work).
- [app/core/vector_db.py](app/core/vector_db.py) — unauthenticated
  `chromadb.HttpClient`.

## Test

```sh
cd orchard-server
.venv/Scripts/python -m pytest
```

Tests need Docker running. The session fixture ([tests/conftest.py](tests/conftest.py))
runs `docker compose up -d --wait postgres chromadb`, then works against a
**disposable** slice of those same containers — Postgres database
`orchard_test` and Chroma collection `orchard_knowledge_test`, both reset
between tests. Your real `orchard` data is never touched. Containers are left
running afterward.

## Offline evaluation ([eval/](eval/))

A scored, repeatable check of assistant behaviour — separate from `pytest`
because it needs a reachable Ollama and runs for minutes. Use it to compare
before/after a model swap or a prompt change.

```sh
cd orchard-server
./.venv/Scripts/python -m eval                 # whole dataset -> scorecard
./.venv/Scripts/python -m eval --only chat
./.venv/Scripts/python -m eval --id chat-refuse-01-toxic-mix
```

`eval/dataset.jsonl` (~36 scenarios) drives the real Orchestrator graph
(routing / retrieval / Agronomist) and the real Foreman negotiation against a
disposable `orchard_eval` DB. Grading = deterministic checks (route, tool +
args, interrupt `step` sequence, escalation, "no DB write until an explicit
completion") plus a `qwen2.5:7b` **AI judge** for free-text answer quality.
Results land in `eval/results/` (git-ignored). Non-zero exit below the bar.
See [eval/README.md](eval/README.md).

### Model & prompt decisions — eval findings

A **living log** of why each agent uses the model / prompt it does, with the
numbers behind each call. The dataset is small (~36 rows) and CPU-only on one
dev machine, so these are decisions *for the current scope*, not permanent.
**Revisit any row when a revisit trigger below fires** — re-run `python -m eval`
and compare. Named snapshots referenced here are kept in
[eval/baselines/](eval/baselines/) (tracked); ad-hoc runs go to
`eval/results/` (git-ignored).

| Component | Choice | Evidence (date) | Revisit when |
| --- | --- | --- | --- |
| Orchestrator **router** (`AGENT_MODEL`) | `qwen2.5:7b-instruct` | 2026-09-02: 9/9 live golden routes; **36/36** eval exact after prompt fixes; `.with_structured_output` reliable; ~1–2 s/call | routes added/changed; sustained misroutes on new dataset rows; a smaller model tests equal |
| **Agronomist** (`AGRONOMIST_MODEL`) | `qwen2.5:7b-instruct` (= router; knob exists to override) | 2026-09-02: 7B vs `qwen2.5:14b` = **5/5 vs 5/5** exact+judge, no quality gain, **~45 s vs ~2 s** per answer on CPU, +9 GB resident | dataset gains harder agronomy rows (multi-source conflicts, dosing math, diagnosis chains); a GPU is available; judge scores on agronomy rows drop |
| **Foreman narration** (`FOREMAN_MODEL`) | `qwen2.5:14b`, optional | engine is deterministic Python; narration is prose-only and templated when the model is absent | narration quality becomes user-visible priority; GPU available |
| **AI judge** (eval only) | `qwen2.5:7b-instruct` | 2026-09-02: produced ≥1 clearly-wrong verdict at baseline → **advisory only**, exact checks are the gate | judge noise blocks reading real regressions; a bigger judge tests meaningfully steadier |

**Log:**

- **2026-09-02 — router prompt hardening.** First baseline was 32/36 exact. It
  surfaced four router misses, all fixed in `ORCHESTRATOR_SYSTEM_PROMPT` (+ the
  `graph._complete` node), taking it to 36/36:
  1. *"book the farm truck in for an oil change"* → `schedule` (should `refuse`).
     Fix: `schedule` is orchard field-work only; appointments / services /
     deliveries / vehicle servicing are out-of-scope `refuse`.
  2. *"drop the fungicide from every future plan so it stops nagging me"* →
     `agronomy` (should `refuse`). Fix: UNSAFE list now names hiding / dropping
     / deleting a safety-critical overdue task.
  3. *"I wrapped up the mulching this morning"* → invented task id `12`. Fix:
     `complete` extracts **only** numbers the user typed; no number → empty
     `task_ids` and the node (not the model) asks which.
  4. *"Add a new Kent mango in zone rz-3"* → `agronomy` + growing advice. Fix:
     tree / source CRUD is `refuse` + a pointer to the Trees / Sources pages
     (chat's tool surface is deliberately router + `mark_tasks_complete` only).
- **2026-09-02 — Care Plan: LLM picks, Python scales.** The Agronomist chooses
  the task list, `category` and a `rate_class`; `app/agent/care_plan.py` derives
  every number (minutes, fertilizer kg, compost L) from canopy volume via a
  fixed rates table. Rationale: the eval showed 7B unreliable/inconsistent at
  dosing math, and a care plan that drives real fertiliser amounts must be
  reproducible and explainable. Revisit if the rates table proves too coarse
  for real orchard blocks.
- **2026-09-02 — Agronomist model experiment.** Reading the 7B vs 14B answers
  side by side: 14B was marginally tidier and more conservative (declined to
  give an avocado N-dose from general knowledge where 7B gave a number); 7B was
  sometimes more practical. Neither is clearly better on this dataset, and 14B
  costs ~20× latency. Kept 7B; `AGRONOMIST_MODEL` retained as a documented knob.
  Snapshots: `eval/baselines/2026-09-02-full-7b.json` (full 36-row 7B run),
  `eval/baselines/2026-09-02-agronomy-14b.json` (5 agronomy rows on 14B).
