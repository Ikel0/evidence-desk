from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def read_document(path: Path) -> str:
    """Read supported local documents without adding a runtime dependency."""
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".html", ".htm"}:
        parser = _TextExtractor()
        parser.feed(raw)
        raw = " ".join(parser.parts)
    return re.sub(r"\s+", " ", raw).strip()


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_text(text: str, size: int = 620, overlap: int = 110) -> list[str]:
    """Split on word boundaries with overlap so citations keep their context."""
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = end - overlap
    return chunks
