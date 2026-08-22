from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .evaluation import evaluate, load_cases
from .rag import answer
from .store import EvidenceStore

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
WEB = ROOT / "web"
STORE = EvidenceStore(DATA / "evidence.db")


def seed_demo() -> None:
    for path in sorted((DATA / "demo").glob("*")):
        if path.suffix.lower() in {".txt", ".md", ".html", ".htm"}:
            STORE.ingest(path)


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
        if self.path == "/api/health":
            self.send_json({"status": "ok", "documents": len(STORE.list_documents())})
            return
        if self.path == "/api/documents":
            self.send_json(STORE.list_documents())
            return
        if self.path == "/api/evaluation":
            try:
                self.send_json(evaluate(STORE, load_cases(ROOT / "eval" / "golden.json")))
            except (OSError, ValueError) as exc:
                self.send_json({"error": "Suite d'évaluation indisponible", "detail": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        super().do_GET()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_json({"error": "JSON invalide"}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/query":
            question = str(payload.get("question", "")).strip()
            if not question:
                self.send_json({"error": "Une question est requise"}, HTTPStatus.BAD_REQUEST)
                return
            self.send_json(answer(STORE, question))
            return
        if self.path == "/api/ingest":
            candidate = (ROOT / str(payload.get("path", ""))).resolve()
            if DATA not in candidate.parents or not candidate.exists():
                self.send_json({"error": "Le fichier doit se trouver dans data/"}, HTTPStatus.BAD_REQUEST)
                return
            self.send_json(STORE.ingest(candidate))
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
