from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .evaluation import evaluate, load_cases
from .rag import answer, candidates
from .store import EvidenceStore

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
WEB = ROOT / "web"
STORE = EvidenceStore(DATA / "evidence.db")


def load_demo_catalog() -> dict[str, dict[str, object]]:
    """Load explicit source ownership for the bundled demonstration corpus."""
    catalog_path = DATA / "demo" / "catalog.json"
    if not catalog_path.exists():
        return {}
    raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not all(isinstance(key, str) and isinstance(value, dict) for key, value in raw.items()):
        raise ValueError("data/demo/catalog.json must map file names to metadata objects")
    return raw


def seed_demo() -> None:
    catalog = load_demo_catalog()
    for path in sorted((DATA / "demo").glob("*")):
        if path.suffix.lower() in {".txt", ".md", ".html", ".htm"}:
            STORE.ingest(path, metadata=catalog.get(path.name))


MIN_LIVE_QUESTION = 3


def read_question(payload: dict[str, object]) -> tuple[str, frozenset[str]]:
    """Validate the question and the sources the reader chose to set aside."""
    raw_question = payload.get("question", "")
    if not isinstance(raw_question, str):
        raise ValueError("La question doit être du texte")
    question = raw_question.strip()
    if not question:
        raise ValueError("Une question est requise")
    if len(question) > 2000:
        raise ValueError("La question est trop longue")
    raw_excluded = payload.get("exclude_sources", [])
    if not isinstance(raw_excluded, list) or len(raw_excluded) > 20 or not all(
        isinstance(item, str) and 0 < len(item) <= 120 for item in raw_excluded
    ):
        raise ValueError("exclude_sources doit être une liste courte d’identifiants de source")
    return question, frozenset(raw_excluded)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json({"status": "ok", "documents": len(STORE.list_documents()), "receipts": len(STORE.list_receipts())})
            return
        if parsed.path == "/api/documents":
            self.send_json(STORE.list_documents())
            return
        if parsed.path == "/api/receipts":
            requested_limit = parse_qs(parsed.query).get("limit", ["20"])[0]
            try:
                limit = int(requested_limit)
            except ValueError:
                self.send_json({"error": "La limite doit être un entier"}, HTTPStatus.BAD_REQUEST)
                return
            self.send_json(STORE.list_receipts(limit))
            return
        if parsed.path == "/api/evaluation":
            try:
                self.send_json(evaluate(STORE, load_cases(ROOT / "eval" / "golden.json")))
            except (OSError, ValueError) as exc:
                self.send_json({"error": "Suite d'évaluation indisponible", "detail": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        super().do_GET()

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 1_000_000:
                raise ValueError("La requête est trop volumineuse")
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, ValueError):
            self.send_json({"error": "JSON invalide"}, HTTPStatus.BAD_REQUEST)
            return
        if not isinstance(payload, dict):
            self.send_json({"error": "Le JSON doit être un objet"}, HTTPStatus.BAD_REQUEST)
            return
        parsed = urlparse(self.path)
        if parsed.path in {"/api/query", "/api/candidates"}:
            try:
                question, excluded = read_question(payload)
            except ValueError as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            if parsed.path == "/api/candidates":
                if len(question) < MIN_LIVE_QUESTION:
                    self.send_json({"error": f"Au moins {MIN_LIVE_QUESTION} caractères sont nécessaires"}, HTTPStatus.BAD_REQUEST)
                    return
                self.send_json(candidates(STORE, question, exclude_sources=excluded))
                return
            # Un exemple affiché à l'ouverture n'est pas une question du visiteur : pas de reçu écrit.
            record = payload.get("preview") is not True
            self.send_json(answer(STORE, question, record_receipt=record, exclude_sources=excluded))
            return
        if parsed.path == "/api/ingest":
            candidate = (ROOT / str(payload.get("path", ""))).resolve()
            if DATA not in candidate.parents or not candidate.is_file():
                self.send_json({"error": "Le fichier doit se trouver dans data/"}, HTTPStatus.BAD_REQUEST)
                return
            metadata = payload.get("metadata")
            if metadata is not None and not isinstance(metadata, dict):
                self.send_json({"error": "Les métadonnées doivent être un objet JSON"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                self.send_json(STORE.ingest(candidate, metadata=metadata))
            except ValueError as exc:
                self.send_json({"error": "Métadonnées invalides", "detail": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self.send_json({"error": "Route inconnue"}, HTTPStatus.NOT_FOUND)


def main() -> None:
    seed_demo()
    port = int(os.getenv("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Evidence Desk running on http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
