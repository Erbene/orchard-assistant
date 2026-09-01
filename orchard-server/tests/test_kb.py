"""Knowledge-base tests: ingestion -> Chroma, tree links, and the REST
endpoint. Runs against the disposable ``orchard_test`` DB and the
``orchard_knowledge_test`` Chroma collection (both reset between tests by
conftest.py). The MiniLM embedding model is cached after the first run."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core import db
from app.dependencies import get_settings_dep
from app.main import app
from app.rag.chunking import chunk_text
from app.rag.vector_store import OrchardVectorStore, get_vector_store
from app.repositories.source_repository import SourceRepository
from app.repositories.tree_repository import TreeRepository
from app.repositories.zone_repository import ZoneRepository
from app.schemas.tree import TreeCreate
from app.services.source_service import SourceService
from app.services.tree_service import TreeService
from app.services.validators import get_default_validation_agent

from conftest import stack_settings

MANGO_DOC = (
    "Young mango trees need deep, infrequent watering to encourage deep roots.\n\n"
    "Structural pruning of a mango should happen in the first three years to "
    "establish a strong scaffold of three or four main limbs.\n\n"
    "Anthracnose is the most common fungal disease of mango in humid climates."
)


def test_chunker_splits_and_overlaps():
    chunks = chunk_text("para one. " * 200 + "\n\n" + "para two. " * 200, chunk_size=400)
    assert len(chunks) >= 3
    assert all(len(c) <= 420 for c in chunks)


@dataclass
class KB:
    sources: SourceService
    trees: TreeService
    store: OrchardVectorStore
    conn: AsyncConnection


@pytest.fixture()
def kb(tmp_path: Path):
    settings = stack_settings(uploads_dir=str(tmp_path / "uploads"))
    store = get_vector_store(settings)

    def run(body):
        async def _wrap():
            try:
                async with db.connection(settings) as conn:
                    tree_repo = TreeRepository(conn)
                    ctx = KB(
                        sources=SourceService(
                            SourceRepository(conn), tree_repo, store, settings
                        ),
                        trees=TreeService(
                            tree_repo, ZoneRepository(conn), get_default_validation_agent()
                        ),
                        store=store,
                        conn=conn,
                    )
                    return await body(ctx)
            finally:
                await db.dispose_all()

        return asyncio.run(_wrap())

    return run


def test_ingest_text_embeds_and_links(kb):
    async def body(c: KB):
        tree = await c.trees.create_tree(TreeCreate(species="mango", variety="Kent"))
        tid = tree.tree_id

        source = await c.sources.ingest_text("Mango care notes", MANGO_DOC)
        assert source.source_type == "text"

        hits = c.store.search("how should I prune a young mango", source_id=source.id)
        assert hits and any("prun" in h.lower() for h in hits)

        linked = await c.sources.set_tree_sources(tid, [source.id])
        assert [s.id for s in linked] == [source.id]
        assert await c.sources.allowed_source_ids(tid) == [source.id]

        with pytest.raises(Exception):
            await c.sources.set_tree_sources(tid, [source.id, 9999])

    kb(body)


def test_delete_source_clears_chunks(kb):
    async def body(c: KB):
        source = await c.sources.ingest_text("notes", MANGO_DOC)
        assert c.store.search("mango", source_id=source.id)
        await c.sources.delete_source(source.id)
        assert c.store.search("mango", source_id=source.id) == []

    kb(body)


def test_consensus_fusion_groups_results_by_source(kb):
    """Mirrors search_knowledge: independent per-source search + headers."""
    async def body(c: KB):
        tree = await c.trees.create_tree(TreeCreate(species="mango", variety="Kent"))
        tid = tree.tree_id
        s1 = await c.sources.ingest_text("Guide A", "Prune young mango to 3 scaffold limbs.")
        s2 = await c.sources.ingest_text(
            "Guide B", "Mango anthracnose is managed with copper sprays."
        )
        await c.sources.set_tree_sources(tid, [s1.id, s2.id])

        blocks = []
        for sid in await c.sources.allowed_source_ids(tid):
            chunks = c.store.search("mango pruning and disease", source_id=sid, n_results=2)
            if chunks:
                blocks.append(f"--- SOURCE {sid} ---\n" + "\n".join(f"- {ch}" for ch in chunks))
        fused = "\n\n".join(blocks)

        assert f"--- SOURCE {s1.id} ---" in fused
        assert f"--- SOURCE {s2.id} ---" in fused

    kb(body)


def test_sources_rest_endpoint_multipart(tmp_path: Path):
    settings = stack_settings(uploads_dir=str(tmp_path / "uploads"))
    app.dependency_overrides[get_settings_dep] = lambda: settings
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
