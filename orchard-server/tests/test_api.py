"""End-to-end tests through the HTTP layer, exercising router -> service ->
repository against a throwaway SQLite file selected via dependency override."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import _initialized, get_settings_dep
from app.main import app


@pytest.fixture()
def client(tmp_path: Path):
    settings = Settings(db_path=str(tmp_path / "test.db"))
    app.dependency_overrides[get_settings_dep] = lambda: settings
    _initialized.discard(settings.db_path)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    _initialized.discard(settings.db_path)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_zone_crud_and_canonicalization(client):
    # free-text synonym -> canonical form
    r = client.post("/zones", json={"zone_id": "north", "name": "North block", "soil_drainage": "sandy"})
    assert r.status_code == 201, r.text
    assert r.json()["soil_drainage"] == "sandy_fast_draining"

    # duplicate id -> 409 from ConflictError
    assert client.post("/zones", json={"zone_id": "north", "name": "dup"}).status_code == 409

    # unknown categorical value -> 422 from DomainValidationError
    bad = client.post("/zones", json={"zone_id": "z9", "name": "x", "soil_drainage": "quicksand"})
    assert bad.status_code == 422
    assert bad.json()["field"] == "soil_drainage"

    assert client.patch("/zones/north", json={"soil_drainage": "loam"}).json()["soil_drainage"] == "loamy"
    assert client.get("/zones/north").json()["name"] == "North block"
    assert client.delete("/zones/north").status_code == 204
    assert client.get("/zones/north").status_code == 404


def test_tree_crud_age_and_fk(client):
    client.post("/zones", json={"zone_id": "z1", "name": "Zone 1"})

    r = client.post(
        "/trees",
        json={"species": "Custard Apple", "variety": "gefner", "zone_id": "z1", "planted_date": "2020-01-01"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    tid = body["tree_id"]
    assert body["species"] == "sugar_apple"      # synonym canonicalized
    assert body["variety"] == "Gefner"           # open text, title-cased
    assert body["age_days"] > 2000 and body["age_years"] >= 5

    # unknown zone -> 422
    assert client.post("/trees", json={"species": "mango", "variety": "x", "zone_id": "nope"}).status_code == 422
    # unrecognized species -> 422
    assert client.post("/trees", json={"species": "banana", "variety": "x"}).status_code == 422

    r = client.patch(f"/trees/{tid}", json={"variety": "nam doc mai", "notes": "grafted"})
    assert r.json()["variety"] == "Nam Doc Mai"
    assert r.json()["notes"] == "grafted"

    assert len(client.get("/trees", params={"zone_id": "z1"}).json()) == 1
    assert client.get("/trees", params={"species": "sapodilla"}).json() == []

    # zone still referenced -> 409
    assert client.delete("/zones/z1").status_code == 409
    assert client.delete(f"/trees/{tid}").status_code == 204
    assert client.get(f"/trees/{tid}").status_code == 404
