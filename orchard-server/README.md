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

## Free-text over enums

Domain fields (`species`, `variety`, `soil_drainage`) are plain `str` on the
wire. Before anything reaches a repository, the **service** calls the
**validation agent** ([app/services/validators.py](app/services/validators.py)):

```python
outcome = await self._validator.validate("species", "Custard Apple")
# -> ValidationOutcome(canonical="sugar_apple", is_valid=True, confidence=1.0, ...)
```

- `StaticVocabularyValidationAgent` (default): deterministic vocabulary +
  synonym matcher. Closed-vocab fields reject unknown values (-> HTTP 422);
  open fields like `variety` are normalized but always accepted.
- `LLMValidationAgent`: placeholder showing where a local model / MCP tool
  call goes, with graceful fallback to the deterministic agent.

Swap implementations in `get_default_validation_agent()` - no service changes.

## MCP / agent reuse

Service methods take and return Pydantic models or plain values and raise
framework-neutral `DomainError`s. A future MCP server can call
`TreeService.create_tree(TreeCreate(...))` directly and map `DomainError` to
tool errors, with zero HTTP coupling.

## Endpoints

| Method | Path | Notes |
| ------ | ---- | ----- |
| `GET`    | `/zones`, `/trees` | list; `/trees` accepts `?species=` / `?zone_id=` |
| `GET`    | `/zones/{id}`, `/trees/{id}` | 404 if missing |
| `POST`   | `/zones`, `/trees` | 201; 409 on duplicate key; 422 on invalid free-text |
| `PATCH`  | `/zones/{id}`, `/trees/{id}` | partial; only supplied fields change |
| `DELETE` | `/zones/{id}`, `/trees/{id}` | 204; 409 deleting a zone a tree still references |

Tree `age_days` / `age_years` are derived from `planted_date` on read, never stored.

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
