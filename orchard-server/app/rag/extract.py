"""Plain-text extraction from uploaded files (PDF / Markdown / plain text)."""
from __future__ import annotations

import io
from pathlib import Path

_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".rst", ".csv"}


class UnsupportedFileType(ValueError):
    pass


def extract_text(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()

    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join(
            (page.extract_text() or "").strip() for page in reader.pages
        ).strip()

    if suffix in _TEXT_SUFFIXES or suffix == "":
        return data.decode("utf-8", errors="replace").strip()

    raise UnsupportedFileType(
        f"unsupported file type {suffix!r}; accepted: PDF, MD, TXT"
    )
