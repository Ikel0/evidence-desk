from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .ingest import chunk_text, fingerprint, read_document


_VALID_AUTHORITIES = {"authoritative", "controlled", "reference", "unclassified"}
_VALID_STATUSES = {"active", "draft", "superseded"}


@dataclass(frozen=True)
class Evidence:
    """A passage plus the source attributes needed to inspect it later."""

    chunk_id: int
    document_id: int
    source_id: str
    document: str
    version: str
    authority: str
    status: str
    owner: str | None
    reviewed_at: str | None
    review_due_at: str | None
    content_hash: str
    position: int
    text: str
    lexical_score: float


class EvidenceStore:
    """SQLite-backed document store with passage-level provenance receipts."""

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
                  source_id TEXT NOT NULL DEFAULT '',
                  version TEXT NOT NULL DEFAULT '',
                  authority TEXT NOT NULL DEFAULT 'unclassified',
                  status TEXT NOT NULL DEFAULT 'active',
                  owner TEXT,
                  reviewed_at TEXT,
                  review_due_at TEXT,
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
                CREATE TABLE IF NOT EXISTS retrieval_receipts (
                  id INTEGER PRIMARY KEY,
                  query_hash TEXT NOT NULL,
                  retrieved_count INTEGER NOT NULL,
                  evidence_hash TEXT NOT NULL,
                  evidence_json TEXT NOT NULL,
                  response_state TEXT NOT NULL,
                  generation TEXT NOT NULL,
                  reason TEXT NOT NULL,
                  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            self._migrate_documents(conn)

    @staticmethod
    def _migrate_documents(conn: sqlite3.Connection) -> None:
        """Keep databases created by the first project version readable."""
        expected = {
            "source_id": "TEXT NOT NULL DEFAULT ''",
            "version": "TEXT NOT NULL DEFAULT ''",
            "authority": "TEXT NOT NULL DEFAULT 'unclassified'",
            "status": "TEXT NOT NULL DEFAULT 'active'",
            "owner": "TEXT",
            "reviewed_at": "TEXT",
            "review_due_at": "TEXT",
        }
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(documents)")}
        for name, definition in expected.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {name} {definition}")
        conn.execute("UPDATE documents SET source_id = 'legacy-' || id WHERE source_id IS NULL OR source_id = ''")
        conn.execute("UPDATE documents SET version = 'sha256-' || substr(content_hash, 1, 12) WHERE version IS NULL OR version = ''")
        conn.execute("UPDATE documents SET authority = 'unclassified' WHERE authority IS NULL OR authority = ''")
        conn.execute("UPDATE documents SET status = 'active' WHERE status IS NULL OR status = ''")

    @staticmethod
    def _clean_text(value: object, field: str, *, required: bool = False) -> str | None:
        if value is None:
            if required:
                raise ValueError(f"{field} is required")
            return None
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a string")
        cleaned = value.strip()
        if required and not cleaned:
            raise ValueError(f"{field} is required")
        return cleaned or None

    def _metadata_for(self, path: Path, digest: str, metadata: dict[str, object] | None) -> dict[str, str | None]:
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        raw: dict[str, object] = metadata or {}
        title = self._clean_text(raw.get("title"), "title") or path.stem.replace("_", " ").title()
        source_id = self._clean_text(raw.get("source_id"), "source_id") or f"local-{path.stem.lower().replace('_', '-')}"
        version = self._clean_text(raw.get("version"), "version") or f"sha256-{digest[:12]}"
        authority = self._clean_text(raw.get("authority"), "authority") or "unclassified"
        status = self._clean_text(raw.get("status"), "status") or "active"
        owner = self._clean_text(raw.get("owner"), "owner")
        reviewed_at = self._clean_text(raw.get("reviewed_at"), "reviewed_at")
        review_due_at = self._clean_text(raw.get("review_due_at"), "review_due_at")
        if authority not in _VALID_AUTHORITIES:
            raise ValueError(f"authority must be one of: {', '.join(sorted(_VALID_AUTHORITIES))}")
        if status not in _VALID_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(_VALID_STATUSES))}")
        for field, value in (("reviewed_at", reviewed_at), ("review_due_at", review_due_at)):
            if value:
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise ValueError(f"{field} must use a valid YYYY-MM-DD date") from exc
        return {
            "title": title,
            "source_id": source_id,
            "version": version,
            "authority": authority,
            "status": status,
            "owner": owner,
            "reviewed_at": reviewed_at,
            "review_due_at": review_due_at,
        }

    def ingest(self, path: Path, metadata: dict[str, object] | None = None) -> dict[str, object]:
        text = read_document(path)
        digest = fingerprint(text)
        source = self._metadata_for(path, digest, metadata)
        values = (
            str(path),
            source["title"],
            source["source_id"],
            source["version"],
            source["authority"],
            source["status"],
            source["owner"],
            source["reviewed_at"],
            source["review_due_at"],
        )
        with self.connect() as conn:
            existing = conn.execute("SELECT id FROM documents WHERE content_hash = ?", (digest,)).fetchone()
            if existing:
                conn.execute(
                    """UPDATE documents
                    SET source_path = ?, title = ?, source_id = ?, version = ?, authority = ?, status = ?,
                        owner = ?, reviewed_at = ?, review_due_at = ?
                    WHERE id = ?""",
                    (*values, existing["id"]),
                )
                return {
                    "status": "unchanged",
                    "chunks": 0,
                    "document_id": existing["id"],
                    "source_id": source["source_id"],
                    "version": source["version"],
                }
            cursor = conn.execute(
                """INSERT INTO documents(
                    source_path, title, content_hash, source_id, version, authority, status, owner, reviewed_at, review_due_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(path), source["title"], digest, *values[2:]),
            )
            document_id = cursor.lastrowid
            # A logical source may be updated while its file hash changes. Keep
            # the current version active and remove older active copies from the
            # answer path so a response cannot mix a policy with its replacement.
            if source["status"] == "active":
                conn.execute(
                    """UPDATE documents SET status = 'superseded'
                    WHERE source_id = ? AND id != ? AND status = 'active'""",
                    (source["source_id"], document_id),
                )
            chunks = chunk_text(text)
            conn.executemany(
                "INSERT INTO chunks(document_id, position, text) VALUES (?, ?, ?)",
                [(document_id, index + 1, item) for index, item in enumerate(chunks)],
            )
            return {
                "status": "indexed",
                "chunks": len(chunks),
                "document_id": document_id,
                "source_id": source["source_id"],
                "version": source["version"],
            }

    def list_documents(self) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT d.id, d.title, d.source_path, d.source_id, d.version, d.authority, d.status,
                          d.owner, d.reviewed_at, d.review_due_at, d.content_hash, d.created_at,
                          COUNT(c.id) AS chunks
                FROM documents d LEFT JOIN chunks c ON c.document_id = d.id
                GROUP BY d.id ORDER BY d.created_at DESC, d.id DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def search(self, query: str, limit: int = 8) -> list[Evidence]:
        stopwords = {
            "avec", "dans", "pour", "quel", "quelle", "quels", "quelles", "sont", "être", "fait", "faire",
            "faut", "qui", "que", "les", "des", "une", "un", "est", "sur", "par", "aux", "ses", "ces",
        }
        tokens = re.findall(r"[a-zà-ÿ0-9]{3,}", query.lower())
        tokens = [token for token in tokens if token not in stopwords]
        terms = " OR ".join(f"{token}*" if len(token) > 4 else token for token in tokens)
        if not terms:
            return []
        safe_limit = max(1, min(int(limit), 50))
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT c.id AS chunk_id, d.id AS document_id, d.source_id, d.title, d.version,
                          d.authority, d.status, d.owner, d.reviewed_at, d.review_due_at, d.content_hash,
                          c.position, c.text, bm25(chunk_fts) AS score
                FROM chunk_fts
                JOIN chunks c ON c.id = chunk_fts.rowid
                JOIN documents d ON d.id = c.document_id
                WHERE chunk_fts MATCH ? AND d.status = 'active'
                ORDER BY score LIMIT ?""",
                (terms, safe_limit),
            ).fetchall()
        return [
            Evidence(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                source_id=row["source_id"],
                document=row["title"],
                version=row["version"],
                authority=row["authority"],
                status=row["status"],
                owner=row["owner"],
                reviewed_at=row["reviewed_at"],
                review_due_at=row["review_due_at"],
                content_hash=row["content_hash"],
                position=row["position"],
                text=row["text"],
                lexical_score=abs(row["score"]),
            )
            for row in rows
        ]

    def record_receipt(
        self,
        question: str,
        evidence: list[Evidence],
        *,
        response_state: str,
        generation: str,
        reason: str,
    ) -> dict[str, object]:
        """Store a privacy-conscious retrieval receipt without storing the question."""
        normalized_question = " ".join(question.lower().split())
        snapshot = [
            {
                "source_id": item.source_id,
                "version": item.version,
                "chunk_id": item.chunk_id,
                "position": item.position,
                "content_hash": item.content_hash,
            }
            for item in evidence
        ]
        evidence_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.connect() as conn:
            cursor = conn.execute(
                """INSERT INTO retrieval_receipts(
                    query_hash, retrieved_count, evidence_hash, evidence_json, response_state, generation, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    fingerprint(normalized_question),
                    len(evidence),
                    fingerprint(evidence_json),
                    evidence_json,
                    response_state,
                    generation,
                    reason,
                ),
            )
            row = conn.execute(
                "SELECT id, query_hash, retrieved_count, evidence_hash, response_state, generation, reason, created_at "
                "FROM retrieval_receipts WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return self._receipt_payload(row)

    @staticmethod
    def _receipt_payload(row: sqlite3.Row) -> dict[str, object]:
        return {
            "id": f"EDR-{row['id']:06d}",
            "query_fingerprint": f"sha256:{row['query_hash'][:16]}",
            "evidence_fingerprint": f"sha256:{row['evidence_hash'][:16]}",
            "retrieved_passages": row["retrieved_count"],
            "state": row["response_state"],
            "generation": row["generation"],
            "reason": row["reason"],
            "recorded_at": row["created_at"],
        }

    def list_receipts(self, limit: int = 20) -> list[dict[str, object]]:
        safe_limit = max(1, min(int(limit), 100))
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT id, query_hash, retrieved_count, evidence_hash, evidence_json, response_state,
                          generation, reason, created_at
                FROM retrieval_receipts ORDER BY id DESC LIMIT ?""",
                (safe_limit,),
            ).fetchall()
        receipts: list[dict[str, object]] = []
        for row in rows:
            receipt = self._receipt_payload(row)
            receipt["evidence"] = json.loads(row["evidence_json"])
            receipts.append(receipt)
        return receipts
