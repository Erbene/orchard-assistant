"""Text chunking for RAG ingestion.

Paragraph-aware sliding window: split on blank lines, then greedily pack
paragraphs into ~``chunk_size`` character windows with ``overlap`` characters
of tail carried into the next chunk.
"""
from __future__ import annotations

import re

_PARA = re.compile(r"\n\s*\n")
_WS = re.compile(r"[ \t]+")


def chunk_text(
    text: str, *, chunk_size: int = 1000, overlap: int = 150
) -> list[str]:
    cleaned = _WS.sub(" ", text.strip())
    if not cleaned:
        return []

    paragraphs = [p.strip() for p in _PARA.split(cleaned) if p.strip()]
    chunks: list[str] = []
    buf = ""

    for para in paragraphs:
        candidate = f"{buf}\n\n{para}".strip() if buf else para
        if len(candidate) <= chunk_size:
            buf = candidate
            continue
        if buf:
            chunks.append(buf)
            buf = (buf[-overlap:] + "\n\n" + para).strip() if overlap else para
        else:
            buf = para
        # a single paragraph longer than chunk_size: hard-split it
        while len(buf) > chunk_size:
            chunks.append(buf[:chunk_size])
            buf = buf[chunk_size - overlap :]

    if buf:
        chunks.append(buf)
    return chunks
