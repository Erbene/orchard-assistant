# Orchard Assistant API

FastAPI + SQLite service for orchard **zones** and **trees**, built as a
clean layered architecture.

## Layers

```
app/
  main.py            composition root: app, routers, exception handlers, lifespan
  config.py          Settings (env-driven, framework-free)
  db.py              sqlite connection + schema bootstrap (no HTTP, no Pydantic)
  dependencies.py    FastAPI Depends() wiring: connection -> repo -> service
  sql/schema.sql     DDL

  api/               HTTP LAYER - request/response, status codes, delegation only
    __init__.py        aggregate router
    errors.py          domain exception -> HTTP status mapping
    routes/
      zones.py
      trees.py

  schemas/           Pydantic transport models (free-text str, no enums)
    zone.py
    tree.py

  services/          BUSINESS LOGIC - HTTP-agnostic, returns Pydantic/plain objects
    zone_service.py
    tree_service.py
    validators.py      Validation Agent interface + placeholder implementations
    exceptions.py      DomainError / NotFoundError / ConflictError / DomainValidationError

  repositories/      PERSISTENCE - raw SQL only, dict rows in/out
    zone_repository.py
    tree_repository.py
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

Tree `age_days` / `age_years` are derived from `planted_date` on read, never stored.

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
