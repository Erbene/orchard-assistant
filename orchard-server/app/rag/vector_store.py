"""ChromaDB wrapper for the orchard knowledge base.

One persistent collection (``orchard_knowledge``). Every chunk carries
``metadata = {"source_id": <sql id>}`` so the Consensus Fusion RAG tool can
run isolated per-source searches with ``where={"source_id": id}``.

Chroma's default embedding (all-MiniLM-L6-v2, ONNX) is downloaded and cached
on first use (~80 MB).
"""
from __future__ import annotations

from functools import lru_cache

import chromadb

from ..config import Settings, get_settings
from ..core.logging import get_logger

_COLLECTION = "orchard_knowledge"
_log = get_logger("app.rag.chroma")


class OrchardVectorStore:
    def __init__(self, path: str) -> None:
        self._client = chromadb.PersistentClient(path=path)
        self._collection = self._client.get_or_create_collection(_COLLECTION)
        _log.info(
            "chroma.ready", path=path, collection=_COLLECTION,
            documents=self._collection.count(),
        )

    def add_source_chunks(self, source_id: int, chunks: list[str]) -> int:
        """Embed and store chunks for one SQL source. Returns the count added."""
        if not chunks:
            return 0
        self._collection.add(
            ids=[f"src-{source_id}-{i}" for i in range(len(chunks))],
            documents=chunks,
            metadatas=[{"source_id": source_id} for _ in chunks],
        )
        return len(chunks)

    def delete_source(self, source_id: int) -> None:
        self._collection.delete(where={"source_id": source_id})

    def search(self, query: str, *, source_id: int, n_results: int = 4) -> list[str]:
        """Semantic search restricted to a single source."""
        result = self._collection.query(
            query_texts=[query],
            n_results=n_results,
            where={"source_id": source_id},
        )
        documents = (result.get("documents") or [[]])[0]
        _log.debug(
            "chroma.search", source_id=source_id, query=query[:120], hits=len(documents)
        )
        return documents

    def search_all(
        self,
        query: str,
        *,
        n_results: int = 12,
        source_ids: list[int] | None = None,
    ) -> list[tuple[int, str]]:
        """Semantic search across the whole KB (or a subset of ``source_ids``).

        Returns ``(source_id, chunk)`` pairs ordered by relevance.
        """
        where = {"source_id": {"$in": source_ids}} if source_ids else None
        result = self._collection.query(
            query_texts=[query], n_results=n_results, where=where
        )
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        pairs = [
            (int(meta.get("source_id", 0)), doc)
            for doc, meta in zip(documents, metadatas)
        ]
        _log.debug(
            "chroma.search_all",
            query=query[:120],
            scope=source_ids or "all",
            hits=len(pairs),
        )
        return pairs


@lru_cache
def get_vector_store(settings: Settings | None = None) -> OrchardVectorStore:
    """Process-wide singleton (the Chroma client is not cheap to build)."""
    return OrchardVectorStore((settings or get_settings()).chroma_path)
