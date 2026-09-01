"""Knowledge-base tests: ingestion -> Chroma, tree links, and the REST
endpoint. Uses a real (tmp-path) Chroma store; the MiniLM embedding model is
cached after the first run."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import connect, init_db
from app.dependencies import _initialized, get_settings_dep
from app.main import app
from app.rag.chunking import chunk_text
from app.rag.vector_store import OrchardVectorStore
from app.repositories.source_repository import SourceRepository
from app.repositories.tree_repository import TreeRepository
from app.schemas.tree import TreeCreate
from app.services.source_service import SourceService
from app.services.tree_service import TreeService
from app.services.validators import get_default_validation_agent

MANGO_DOC = (
    "Young mango trees need deep, infrequent watering to encourage deep roots.\n\n"
    "Structural pruning of a mango should happen in the first three years to "
    "establish a strong scaffold of three or four main limbs.\n\n"
    "Anthracnose is the most common fungal disease of mango in humid climates."
)


def run(coro):
    return asyncio.run(coro)


def test_chunker_splits_and_overlaps():
    chunks = chunk_text("para one. " * 200 + "\n\n" + "para two. " * 200, chunk_size=400)
    assert len(chunks) >= 3
    assert all(len(c) <= 420 for c in chunks)


@pytest.fixture()
def kb(tmp_path: Path):
    settings = Settings(
        db_path=str(tmp_path / "kb.db"),
        chroma_path=str(tmp_path / "chroma"),
        uploads_dir=str(tmp_path / "uploads"),
    )
    init_db(settings)
    conn = connect(settings)
    store = OrchardVectorStore(settings.chroma_path)
    trees = TreeRepository(conn)
    svc = SourceService(SourceRepository(conn), trees, store, settings)
    tree_svc = TreeService(trees, None, get_default_validation_agent())  # type: ignore[arg-type]
    try:
        yield svc, tree_svc, store, conn
    finally:
        conn.commit()
        conn.close()


def test_ingest_text_embeds_and_links(kb):
    svc, tree_svc, store, _ = kb
    tid = run(tree_svc.create_tree(TreeCreate(species="mango", variety="Kent"))).tree_id

    source = run(svc.ingest_text("Mango care notes", MANGO_DOC))
    assert source.source_type == "text"

    hits = store.search("how should I prune a young mango", source_id=source.id)
    assert hits and any("prun" in h.lower() for h in hits)

    linked = run(svc.set_tree_sources(tid, [source.id]))
    assert [s.id for s in linked] == [source.id]
    assert svc.allowed_source_ids(tid) == [source.id]

    # unknown source id rejected
    with pytest.raises(Exception):
        run(svc.set_tree_sources(tid, [source.id, 9999]))


def test_delete_source_clears_chunks(kb):
    svc, _, store, _ = kb
    source = run(svc.ingest_text("notes", MANGO_DOC))
    assert store.search("mango", source_id=source.id)
    run(svc.delete_source(source.id))
    assert store.search("mango", source_id=source.id) == []


def test_consensus_fusion_groups_results_by_source(kb):
    """Mirrors search_ag_knowledge: independent per-source search + headers."""
    svc, tree_svc, store, _ = kb
    tid = run(tree_svc.create_tree(TreeCreate(species="mango", variety="Kent"))).tree_id
    s1 = run(svc.ingest_text("Guide A", "Prune young mango to 3 scaffold limbs."))
    s2 = run(svc.ingest_text("Guide B", "Mango anthracnose is managed with copper sprays."))
    run(svc.set_tree_sources(tid, [s1.id, s2.id]))

    blocks = []
    for sid in svc.allowed_source_ids(tid):
        chunks = store.search("mango pruning and disease", source_id=sid, n_results=2)
        if chunks:
            blocks.append(f"--- SOURCE {sid} ---\n" + "\n".join(f"- {c}" for c in chunks))
    fused = "\n\n".join(blocks)

    assert f"--- SOURCE {s1.id} ---" in fused
    assert f"--- SOURCE {s2.id} ---" in fused


def test_sources_rest_endpoint_multipart(tmp_path: Path):
    settings = Settings(
        db_path=str(tmp_path / "api.db"),
        chroma_path=str(tmp_path / "chroma"),
        uploads_dir=str(tmp_path / "uploads"),
    )
    app.dependency_overrides[get_settings_dep] = lambda: settings
    _initialized.discard(settings.db_path)
    try:
        with TestClient(app) as c:
            # text payload
            r = c.post("/api/v1/sources", data={"name": "Text src", "text": MANGO_DOC})
            assert r.status_code == 201, r.text
            sid = r.json()["id"]

            # file upload
            r = c.post(
                "/api/v1/sources",
                data={"name": "File src"},
                files={"file": ("guide.md", b"# Sapodilla\n\nSapodilla tolerates drought well.", "text/markdown")},
            )
            assert r.status_code == 201, r.text

            assert len(c.get("/api/v1/sources").json()) == 2
            assert c.get(f"/api/v1/sources/{sid}").json()["raw_content"].startswith("Young mango")

            # link to a tree
            tree = c.post("/api/v1/trees", json={"species": "mango", "variety": "Haden"}).json()
            r = c.put(f"/api/v1/trees/{tree['tree_id']}/sources", json={"source_ids": [sid]})
            assert r.status_code == 200 and [s["id"] for s in r.json()] == [sid]
            assert [s["id"] for s in c.get(f"/api/v1/trees/{tree['tree_id']}/sources").json()] == [sid]

            assert c.delete(f"/api/v1/sources/{sid}").status_code == 204
    finally:
        app.dependency_overrides.clear()
        _initialized.discard(settings.db_path)
