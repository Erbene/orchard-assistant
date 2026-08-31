# Orchard Assistant API

A minimal FastAPI + SQLite HTTP service exposing CRUD for two entities:

| Entity | Route prefix | Key |
| ------ | ------------ | --- |
| `zone` | `/zones`     | `zone_id` (text, client-supplied) |
| `tree` | `/trees`     | `tree_id` (int, auto-assigned unless provided) |

## Run

```sh
cd services
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # POSIX
uvicorn api.main:app --reload
```

- Interactive docs: http://127.0.0.1:8000/docs
- Health check: `GET /health`
- Database file defaults to `services/orchard.db`; override with `ORCHARD_DB_PATH`.

## Endpoints

Both entities support the standard set:

| Method | Path | Notes |
| ------ | ---- | ----- |
| `GET`    | `/zones`, `/trees` | list; `/trees` accepts `?species=` and `?zone_id=` filters |
| `GET`    | `/zones/{id}`, `/trees/{id}` | 404 if missing |
| `POST`   | `/zones`, `/trees` | 201 on success, 409 on duplicate key |
| `PATCH`  | `/zones/{id}`, `/trees/{id}` | partial update; only supplied fields change |
| `DELETE` | `/zones/{id}`, `/trees/{id}` | 204; deleting a zone still referenced by a tree returns 409 |

### Validation

- `tree.species` must be `mango`, `sapodilla`, or `sugar_apple`.
- `zone.soil_drainage` must be `sandy_fast_draining`, `loamy`, or omitted/null.
- `tree.zone_id`, when given, must reference an existing zone (422 otherwise).
- `tree.planted_date` is an ISO date. Age is **derived** on read (`age_days`,
  `age_years`) and never stored.

## Test

```sh
cd services
.venv/Scripts/python -m pytest
```
