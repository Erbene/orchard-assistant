"""Knowledge-base source business logic: ingestion (text/file -> chunks ->
ChromaDB), CRUD, and tree<->source linking.

HTTP-agnostic; returns pure Pydantic models.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..config import Settings
from ..core.logging import get_logger
from ..rag.chunking import chunk_text
from ..rag.extract import UnsupportedFileType, extract_text
from ..rag.vector_store import OrchardVectorStore
from ..repositories.source_repository import SourceRepository
from ..repositories.tree_repository import TreeRepository
from ..schemas.source import SourceDetail, SourceRead
from .exceptions import DomainValidationError, NotFoundError

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_log = get_logger("app.rag")


class SourceService:
    def __init__(
        self,
        sources: SourceRepository,
        trees: TreeRepository,
        store: OrchardVectorStore,
        settings: Settings,
    ) -> None:
        self._sources = sources
        self._trees = trees
        self._store = store
        self._settings = settings

    # -- reads / CRUD ---------------------------------------------

    async def list_sources(self) -> list[SourceRead]:
        return [SourceRead.model_validate(r) for r in self._sources.list()]

    async def get_source(self, source_id: int) -> SourceDetail:
        row = self._sources.get(source_id)
        if row is None:
            raise NotFoundError(f"source {source_id} not found")
        return SourceDetail.model_validate(row)

    async def rename_source(self, source_id: int, name: str) -> SourceRead:
        row = self._sources.rename(source_id, name.strip())
        if row is None:
            raise NotFoundError(f"source {source_id} not found")
        return SourceRead.model_validate(row)

    async def delete_source(self, source_id: int) -> None:
        if not self._sources.exists(source_id):
            raise NotFoundError(f"source {source_id} not found")
        self._store.delete_source(source_id)  # drop its chunks from Chroma
        self._sources.delete(source_id)       # FK cascade clears tree_sources
        _log.info("rag.source.deleted", source_id=source_id)

    # -- ingestion ----------------------------------------------

    async def ingest_text(self, name: str, text: str) -> SourceRead:
        if not text.strip():
            raise DomainValidationError("text", "text payload is empty")
        row = self._sources.create(
            name=name.strip(), source_type="text", raw_content=text
        )
        self._embed(row["id"], text)
        _log.info(
            "rag.source.ingested",
            source_id=row["id"], name=row["name"], source_type="text", chars=len(text),
        )
        return SourceRead.model_validate(row)

    async def ingest_file(
        self, name: str, filename: str, data: bytes
    ) -> SourceRead:
        try:
            text = extract_text(filename, data)
        except UnsupportedFileType as exc:
            raise DomainValidationError("file", str(exc)) from exc
        if not text.strip():
            raise DomainValidationError("file", "no extractable text in file")

        row = self._sources.create(
            name=name.strip(), source_type="file", raw_content=text
        )
        path = self._save_upload(row["id"], filename, data)
        self._sources.set_file_path(row["id"], str(path))
        self._embed(row["id"], text)
        _log.info(
            "rag.source.ingested",
            source_id=row["id"], name=row["name"], source_type="file",
            filename=filename, extracted_chars=len(text),
        )
        return SourceRead.model_validate({**row, "file_path": str(path)})

    # -- tree <-> source links ---------------------------------

    async def sources_for_tree(self, tree_id: int) -> list[SourceRead]:
        self._require_tree(tree_id)
        return [
            SourceRead.model_validate(r)
            for r in self._sources.sources_for_tree(tree_id)
        ]

    async def set_tree_sources(
        self, tree_id: int, source_ids: list[int]
    ) -> list[SourceRead]:
        self._require_tree(tree_id)
        missing = [sid for sid in source_ids if not self._sources.exists(sid)]
        if missing:
            raise DomainValidationError(
                "source_ids", f"unknown source id(s): {missing}"
            )
        self._sources.set_tree_links(tree_id, source_ids)
        _log.info("rag.source.linked", tree_id=tree_id, source_ids=source_ids)
        return await self.sources_for_tree(tree_id)

    def allowed_source_ids(self, tree_id: int) -> list[int]:
        """Source ids linked to a tree (used to scope the RAG fusion tool)."""
        return self._sources.source_ids_for_tree(tree_id)

    # -- retrieval --------------------------------------------

    async def search(
        self, query: str, *, source_ids: list[int] | None = None, per_source: int = 4
    ) -> list[dict[str, object]]:
        """Consensus-fusion retrieval.

        ``source_ids=None`` searches the entire knowledge base; otherwise only
        the given sources. Results are grouped by source:
        ``[{"source_id", "name", "chunks": [...]}, ...]`` ordered by relevance.
        """
        if source_ids is not None and not source_ids:
            return []

        if source_ids is None:
            pairs = self._store.search_all(query, n_results=per_source * 4)
        else:
            pairs = []
            for sid in source_ids:
                pairs += [
                    (sid, chunk)
                    for chunk in self._store.search(
                        query, source_id=sid, n_results=per_source
                    )
                ]

        names = {row["id"]: row["name"] for row in self._sources.list()}
        grouped: dict[int, list[str]] = {}
        for sid, chunk in pairs:
            grouped.setdefault(sid, []).append(chunk)

        _log.info(
            "rag.search",
            query=query[:120],
            scope=source_ids or "all",
            sources_hit=len(grouped),
            chunks=sum(len(c) for c in grouped.values()),
        )
        return [
            {"source_id": sid, "name": names.get(sid, f"source {sid}"), "chunks": chunks}
            for sid, chunks in grouped.items()
        ]

    # -- helpers ----------------------------------------------

    def _embed(self, source_id: int, text: str) -> int:
        chunks = chunk_text(text)
        _log.debug(
            "rag.embed.start", source_id=source_id, chunks=len(chunks), chars=len(text)
        )
        added = self._store.add_source_chunks(source_id, chunks)
        _log.info("rag.embed.done", source_id=source_id, chunks=added)
        return added

    def _save_upload(self, source_id: int, filename: str, data: bytes) -> Path:
        uploads = Path(self._settings.uploads_dir)
        uploads.mkdir(parents=True, exist_ok=True)
        safe = _SAFE.sub("_", Path(filename).name) or "upload"
        path = uploads / f"{source_id}__{safe}"
        path.write_bytes(data)
        return path

    def _require_tree(self, tree_id: int) -> None:
        if self._trees.get(tree_id) is None:
            raise NotFoundError(f"tree {tree_id} not found")
