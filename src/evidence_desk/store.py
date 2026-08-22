from __future__ import annotations

import sqlite3
import re
from dataclasses import dataclass
from pathlib import Path

from .ingest import chunk_text, fingerprint, read_document


@dataclass(frozen=True)
class Evidence:
    chunk_id: int
    document: str
    version: str
    position: int
    text: str
    lexical_score: float


class EvidenceStore:
    def __init__(self, database: Path) -> None:
        self.database = database
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                  id INTEGER PRIMARY KEY,
                  source_path TEXT NOT NULL,
                  title TEXT NOT NULL,
                  content_hash TEXT NOT NULL UNIQUE,
                  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS chunks (
                  id INTEGER PRIMARY KEY,
                  document_id INTEGER NOT NULL REFERENCES documents(id),
                  position INTEGER NOT NULL,
                  text TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
                  text, content='chunks', content_rowid='id'
                );
                CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
                  INSERT INTO chunk_fts(rowid, text) VALUES (new.id, new.text);
                END;
                """
            )

    def ingest(self, path: Path) -> dict[str, object]:
        text = read_document(path)
        digest = fingerprint(text)
        with self.connect() as conn:
            existing = conn.execute("SELECT id FROM documents WHERE content_hash = ?", (digest,)).fetchone()
            if existing:
                return {"status": "unchanged", "chunks": 0, "document_id": existing["id"]}
            cursor = conn.execute(
                "INSERT INTO documents(source_path, title, content_hash) VALUES (?, ?, ?)",
                (str(path), path.stem.replace("_", " ").title(), digest),
            )
            document_id = cursor.lastrowid
            chunks = chunk_text(text)
            conn.executemany(
                "INSERT INTO chunks(document_id, position, text) VALUES (?, ?, ?)",
                [(document_id, index + 1, item) for index, item in enumerate(chunks)],
            )
            return {"status": "indexed", "chunks": len(chunks), "document_id": document_id}

    def list_documents(self) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT d.id, d.title, d.source_path, d.created_at, COUNT(c.id) AS chunks
                FROM documents d LEFT JOIN chunks c ON c.document_id = d.id
                GROUP BY d.id ORDER BY d.created_at DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def search(self, query: str, limit: int = 8) -> list[Evidence]:
        stopwords = {"avec", "dans", "pour", "quel", "quelle", "quels", "quelles", "sont", "être", "fait", "faire", "faut", "qui", "que", "les", "des", "une", "un", "est", "sur", "par", "aux", "ses", "ces"}
        # FTS5 query syntax treats punctuation as operators. Keep only lexical
        # terms so a natural French question such as "d'accès" remains safe.
        tokens = re.findall(r"[a-zà-ÿ0-9]{3,}", query.lower())
        tokens = [token for token in tokens if token not in stopwords]
        terms = " OR ".join(f"{token}*" if len(token) > 4 else token for token in tokens)
        if not terms:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT c.id, d.title, d.content_hash, c.position, c.text, bm25(chunk_fts) AS score
                FROM chunk_fts
                JOIN chunks c ON c.id = chunk_fts.rowid
                JOIN documents d ON d.id = c.document_id
                WHERE chunk_fts MATCH ?
                ORDER BY score LIMIT ?""",
                (terms, limit),
            ).fetchall()
        return [
            Evidence(row["id"], row["title"], row["content_hash"][:8], row["position"], row["text"], abs(row["score"]))
            for row in rows
        ]
