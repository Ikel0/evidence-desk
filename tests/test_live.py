import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from evidence_desk import server
from evidence_desk.rag import answer, candidates
from evidence_desk.store import EvidenceStore

DEMO = Path(__file__).resolve().parents[1] / "data" / "demo"
INCIDENT = "Quand faut-il prévenir le responsable de service lors d’un incident élevé ?"
TWO_SOURCES = "Qui valide une demande d’accès et quand prévenir le responsable lors d’un incident ?"


def demo_store(root: Path) -> EvidenceStore:
    catalog = json.loads((DEMO / "catalog.json").read_text(encoding="utf-8"))
    store = EvidenceStore(root / "evidence.db")
    for path in sorted(DEMO.glob("*.md")):
        store.ingest(path, metadata=catalog.get(path.name))
    return store


class LiveSearchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = demo_store(Path(self.directory.name))

    def tearDown(self):
        self.directory.cleanup()

    def test_candidates_follow_fts_order_and_flag_what_the_answer_keeps(self):
        result = candidates(self.store, INCIDENT)
        rows = result["candidates"]
        self.assertTrue(rows)
        self.assertEqual([row["rank"] for row in rows], list(range(1, len(rows) + 1)))
        scores = [row["bm25"] for row in rows]
        self.assertEqual(scores, sorted(scores, reverse=True))
        kept = {row["citation"] for row in rows if row["retained"]}
        cited = {source["citation"] for source in answer(self.store, INCIDENT, record_receipt=False)["sources"]}
        self.assertEqual(kept, cited)
        self.assertFalse(result["would_abstain"])

    def test_candidates_never_write_a_receipt(self):
        candidates(self.store, INCIDENT)
        answer(self.store, INCIDENT, record_receipt=False)
        self.assertEqual(self.store.list_receipts(), [])

    def test_setting_aside_the_only_source_turns_the_answer_into_an_abstention(self):
        before = answer(self.store, INCIDENT, record_receipt=False)
        self.assertEqual(before["state"], "grounded")
        source_id = before["sources"][0]["source_id"]
        after = answer(self.store, INCIDENT, record_receipt=False, exclude_sources=frozenset({source_id}))
        self.assertEqual(after["state"], "insufficient_evidence")
        self.assertEqual(after["sources"], [])
        self.assertEqual(after["retrieval"]["excluded_sources"], [source_id])
        live = candidates(self.store, INCIDENT, exclude_sources=frozenset({source_id}))
        self.assertTrue(live["would_abstain"])
        self.assertTrue(all(row["excluded"] for row in live["candidates"] if row["source_id"] == source_id))

    def test_setting_aside_one_of_two_sources_keeps_the_other_citation(self):
        before = answer(self.store, TWO_SOURCES, record_receipt=False)
        ids = {source["source_id"] for source in before["sources"]}
        self.assertEqual(ids, {"POL-ACCESS-001", "RUN-INC-002"})
        after = answer(self.store, TWO_SOURCES, record_receipt=False, exclude_sources=frozenset({"POL-ACCESS-001"}))
        self.assertEqual({source["source_id"] for source in after["sources"]}, {"RUN-INC-002"})
        self.assertNotIn("sensible", after["answer"])


class QuietHandler(server.Handler):
    def log_message(self, *args):
        pass


class LiveEndpointTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.original_store = server.STORE
        server.STORE = demo_store(Path(self.directory.name))
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        server.STORE = self.original_store
        self.directory.cleanup()

    def post(self, path, payload):
        request = Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_live_search_refuses_fewer_than_three_characters(self):
        status, payload = self.post("/api/candidates", {"question": "ac"})
        self.assertEqual(status, 400)
        self.assertIn("3", payload["error"])
        status, payload = self.post("/api/candidates", {"question": "accès sensible"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["candidates"])

    def test_preview_query_answers_without_writing_a_receipt(self):
        status, payload = self.post("/api/query", {"question": INCIDENT, "preview": True})
        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "grounded")
        self.assertTrue(payload["receipt"]["preview"])
        self.assertEqual(server.STORE.list_receipts(), [])
        self.post("/api/query", {"question": INCIDENT})
        self.assertEqual(len(server.STORE.list_receipts()), 1)

    def test_exclusions_must_be_a_short_list_of_identifiers(self):
        status, _ = self.post("/api/query", {"question": INCIDENT, "exclude_sources": "RUN-INC-002"})
        self.assertEqual(status, 400)
        status, payload = self.post("/api/query", {"question": INCIDENT, "exclude_sources": ["RUN-INC-002"], "preview": True})
        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "insufficient_evidence")


if __name__ == "__main__":
    unittest.main()
