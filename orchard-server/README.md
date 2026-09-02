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
    routes/          zones.py  trees.py  sources.py  chat.py

  schemas/           Pydantic transport models (free-text str, no enums)
    zone.py  tree.py  task.py  source.py  chat.py

  services/          BUSINESS LOGIC - HTTP-agnostic, returns Pydantic/plain objects
    rachio.py  tree_service.py  task_service.py  source_service.py  chat_service.py
    validators.py  exceptions.py

  repositories/      PERSISTENCE - raw SQL only, dict rows in/out (no zone repo - Rachio)
    tree_repository.py  task_repository.py  source_repository.py
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

- `task`: `id`, `tree_id`, `action_type` (free text), `status`
  (`pending`/`completed`/`deferred` — a real state field, so it *is*
  constrained), `priority_score` (float), `scheduled_date` (ISO datetime, nullable),
  `frequency_days` (int, nullable — set = recurring), **`estimated_minutes`**
  (int, nullable), **`required_resources`** (JSON list of free-text names),
  `created_at`, `completed_at`.
- `TaskService`: `create_task` (FK-checked), `mark_complete` (stamps
  `completed_at`, spawns the next occurrence — carries minutes + resources
  forward), `defer_task`, `batch_update_priorities` (atomic),
  `create_baseline_tasks(tree_id, items)` — items are **LLM-supplied** and each
  MUST carry `estimated_minutes` + `required_resources`.
- `TaskRepository.list_pending(scheduled_before=…)` — pending only, `priority_score`
  DESC; the date filter keeps due-by tasks plus unscheduled ones.

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
(async `StateGraph`, no checkpointer — history arrives with every request)
dispatches it:

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

### Chat (SSE)

`POST /api/v1/chat` takes `{ "messages": [{ "role": "user", "content": "…" }] }`
and streams the Orchestrator turn as Server-Sent Events:

```
data: {"type":"start"}
data: {"type":"tool","toolName":"mark_tasks_complete","args":{"task_ids":[3,5]},"result":[3,5]}
data: {"type":"text-delta","delta":"Marked "}
data: {"type":"redirect","href":"/schedule","label":"Open the scheduler"}
data: {"type":"finish","finishReason":"ok"}
```

[app/services/chat_service.py](app/services/chat_service.py) runs the
Orchestrator graph (see above) and yields these event dicts; the route wraps
each as an SSE frame and prepends a preflight `GET {OLLAMA_BASE_URL}/api/version`
— on failure the endpoint returns **503** *before* the stream opens. The
service opens its **own** DB connection for the turn (a request-scoped
`Depends` connection is torn down before a `StreamingResponse` body drains).
`orchard-web` `/assistant` renders the deltas, the completed-tool chip, and the
"Open the scheduler" button.

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

**Local LLM (Ollama).** The Orchestrator/Agronomist need `AGENT_MODEL`
(default `qwen2.5:7b-instruct`) — `/api/v1/chat` is **503** without a reachable
Ollama. The Foreman's narration uses `FOREMAN_MODEL` (default `qwen2.5:14b`)
and is *optional* (templated fallback). `OLLAMA_BASE_URL` defaults to
`http://localhost:11434` (bare-metal) / `http://host.docker.internal:11434`
(compose).

```sh
ollama serve
ollama pull qwen2.5:7b-instruct     # required for chat
ollama pull qwen2.5:14b             # optional, Foreman narration
```

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
