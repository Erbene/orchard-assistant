# Orchard Assistant API

FastAPI + SQLite service for orchard **zones**, **trees** and **tasks**, built
as a clean layered architecture. No ORM — DDL lives in `sql/schema.sql`,
repositories issue raw SQL and return `dict` rows, and "models" are the
Pydantic schemas in `schemas/`.

## Layers

```
app/
  main.py            composition root: app, routers, exception handlers, lifespan
  config.py          Settings (env-driven, framework-free)
  db.py              sqlite connection + schema bootstrap (no HTTP, no Pydantic)
  dependencies.py    FastAPI Depends() wiring: connection -> repo -> service
  mcp_server.py      FastMCP server: service logic as MCP tools + resource (SSE + stdio)
  sql/schema.sql     DDL
  rag/               chunking, file text extraction, ChromaDB wrapper
  agent/             LangGraph orchestration skeleton (state / graph / MCP client)

  api/               HTTP LAYER - request/response, status codes, delegation only
    routes/          zones.py  trees.py  sources.py  chat.py

  schemas/           Pydantic transport models (free-text str, no enums)
    zone.py  tree.py  task.py  source.py  chat.py

  services/          BUSINESS LOGIC - HTTP-agnostic, returns Pydantic/plain objects
    zone_service.py  tree_service.py  task_service.py  source_service.py  chat_service.py
    validators.py  exceptions.py

  repositories/      PERSISTENCE - raw SQL only, dict rows in/out
    zone_repository.py  tree_repository.py  task_repository.py  source_repository.py
```

**Dependency flow (per request):**
`get_settings_dep -> get_connection -> {get_zone_repository, get_tree_repository} + get_validation_agent -> {get_zone_service, get_tree_service} -> route handler`

FastAPI caches sub-dependencies per request, so one `sqlite3.Connection` is
shared by every repository in a request and the request behaves as a single
transaction (commit on success, rollback on exception).

## Free text, no enums

Descriptive fields (`species`, `variety`, `soil_drainage`, `water_source`) are plain
`str` and are **stored exactly as typed** - no enums, no closed vocabularies,
never rejected for being "unrecognized". Before a write, the **service** still
awaits the **validation agent** hook
([app/services/validators.py](app/services/validators.py)):

```python
outcome = await self._validator.validate("soil_drainage", "  fast ")
# -> ValidationOutcome(canonical="fast", is_valid=True)   # whitespace trimmed only
```

- `PassthroughValidationAgent` (default): collapses whitespace, accepts
  everything.
- `LLMValidationAgent`: placeholder showing where a local model / MCP tool
  call goes (for *enrichment*, not gatekeeping), with graceful fallback to
  passthrough.

Swap implementations in `get_default_validation_agent()` - no service changes.
The only 422 the write path still raises is the tree → zone referential check
(`zone_id` must exist).

`zone_id` is an auto-incrementing integer assigned by the database; `POST
/api/v1/zones` takes `{ name, soil_drainage?, water_source? }` with no id.

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
| `GET`    | `/api/v1/zones`, `/api/v1/trees` | list; `/trees` accepts `?species=` / `?zone_id=` |
| `GET`    | `/api/v1/zones/{id}`, `/api/v1/trees/{id}` | 404 if missing |
| `POST`   | `/api/v1/zones`, `/api/v1/trees` | 201; `zone_id`/`tree_id` auto-assigned; 422 only if a tree names a non-existent `zone_id` |
| `PATCH`  | `/api/v1/zones/{id}`, `/api/v1/trees/{id}` | partial; only supplied fields change |
| `DELETE` | `/api/v1/zones/{id}`, `/api/v1/trees/{id}` | 204; 409 deleting a zone a tree still references |
| `GET/POST` | `/api/v1/sources` | KB sources; `POST` is `multipart/form-data` (`name` + `text` OR `file`) |
| `GET` | `/api/v1/sources/{id}` | includes `raw_content` |
| `PATCH/DELETE` | `/api/v1/sources/{id}` | rename (`{name}`) / delete (also purges Chroma chunks) |
| `GET/PUT` | `/api/v1/trees/{id}/sources` | list / replace the sources linked to a tree |

Tree `age_days` / `age_years` are derived from `planted_date` on read, never stored.

### Tasks (JIT scheduling model — service + MCP only)

`task` (FK → `tree`, `ON DELETE CASCADE`), reached through the MCP tools below.
**No REST routers yet.** `user_context` was **dropped** — scheduling
constraints (available minutes, resources) are now gathered *just in time* in
conversation by the agent, not stored.

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

**No manual migration:** `init_db` runs the DDL (`DROP TABLE IF EXISTS
user_context`, `CREATE TABLE IF NOT EXISTS sources/tree_sources`) and
`ALTER TABLE task ADD COLUMN` for the two new columns on an existing DB.

### Knowledge base (Consensus Fusion RAG)

`sources` (`id`, `name`, `source_type` `file`|`text`, `file_path`,
`raw_content`, `upload_date`) + `tree_sources` (`tree_id`, `source_id`) mapping.
`POST /api/v1/sources` extracts text (PDF via `pypdf`, MD/TXT decoded), chunks
it (`app/rag/chunking.py`), and adds every chunk to one ChromaDB collection
with `metadata = {"source_id": <id>}`. `search_ag_knowledge` (MCP) then runs an
**independent** vector search per linked source and returns the results grouped
under `--- SOURCE {id} ---` headers, so the agent does the fusion itself.
Chroma persists at `ORCHARD_CHROMA_PATH` (default `./chroma`); uploaded files at
`ORCHARD_UPLOADS_DIR`. First ingest downloads the MiniLM embedding model (~80 MB).

### Agent skeleton (`app/agent/`)

LangGraph `StateGraph(AgentState)` — `AgentState = {messages, active_tree_id,
available_minutes, confirmed_resources}`. Nodes `orchestrator` → `{agronomist,
foreman}`; the **Foreman** node does the JIT multi-turn check (returns a
question and ends the turn when `available_minutes` is `None`). Nodes are stubs
(no LLM); `app/agent/client.py` binds the MCP tools via
`langchain-mcp-adapters`. LangSmith tracing via `LANGCHAIN_*` env vars — see
`.env.example`.

### Chat (SSE)

`POST /api/v1/chat` takes `{ "messages": [{ "role": "user", "content": "…" }] }`
and streams the reply as Server-Sent Events:

```
data: {"type":"start"}
data: {"type":"text-delta","delta":"Hello "}
data: {"type":"finish","finishReason":"stub"}
```

**No language model is wired up.** [app/services/chat_service.py](app/services/chat_service.py)
returns a stub reply, token by token, so the transport and the `orchard-web`
chat UI work end to end. Replace `ChatService.stream_reply` with a real agent
loop — the signature (message history in, async iterator of text chunks out)
is meant to stay.

## MCP server

[app/mcp_server.py](app/mcp_server.py) exposes the same `ZoneService` /
`TreeService` logic as MCP tools + a resource, for AI-agent clients. It reuses
the service layer directly (one short-lived SQLite connection per call,
wrapped in a transaction) — no HTTP calls to self.

**Tools:**
- zones — `list_zones`, `get_zone_details`, `create_zone`, `update_zone`, `delete_zone`
- trees — `list_trees`, `get_tree_details`, `create_tree`, `update_tree`, `delete_tree`
- tasks (Foreman) — `get_pending_tasks`, `get_task_details`, `create_task`,
  `create_baseline_tasks`, `batch_update_task_priorities`, `mark_task_complete`, `defer_task`
  (`create_task` / `create_baseline_tasks` require the LLM to supply
  `estimated_minutes` + `required_resources`)
- knowledge (Agronomist) — `search_ag_knowledge(tree_id, query)` — consensus-fusion RAG

**Resource:** `orchard://system-summary` — zone/tree/task/source counts + status.

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

## Run

```sh
cd orchard-server
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
uvicorn app.main:app --reload
```

Docs: http://127.0.0.1:8000/docs · DB path via `ORCHARD_DB_PATH` (default `orchard-server/orchard.db`).

## Test

```sh
cd orchard-server
.venv/Scripts/python -m pytest
```
