import tempfile
import unittest
from pathlib import Path

from evidence_desk.evaluation import evaluate
from evidence_desk.rag import answer
from evidence_desk.store import EvidenceStore


class RAGTests(unittest.TestCase):
    def test_answer_contains_a_traceable_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = root / "access.md"
            policy.write_text("Les accès sensibles sont validés par le responsable métier et la sécurité.", encoding="utf-8")
            store = EvidenceStore(root / "evidence.db")
            store.ingest(policy)
            result = answer(store, "Qui valide les accès sensibles ?")
            self.assertTrue(result["sources"])
            self.assertIn("responsable métier", result["answer"].lower())

    def test_ingestion_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "policy.md"
            source.write_text("Une politique de test avec suffisamment de contenu.", encoding="utf-8")
            store = EvidenceStore(root / "evidence.db")
            self.assertEqual(store.ingest(source)["status"], "indexed")
            self.assertEqual(store.ingest(source)["status"], "unchanged")

    def test_common_words_do_not_dilute_retrieval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            access = root / "access.md"
            incident = root / "incident.md"
            access.write_text("Les accès sensibles sont validés par le responsable métier.", encoding="utf-8")
            incident.write_text("Un incident est déclaré après une panne critique.", encoding="utf-8")
            store = EvidenceStore(root / "evidence.db")
            store.ingest(access)
            store.ingest(incident)
            result = answer(store, "Qui valide les accès sensibles ?")
            self.assertIn("responsable métier", result["answer"].lower())

    def test_evaluation_separates_retrieval_from_grounding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = root / "access.md"
            policy.write_text("Les accès sensibles sont validés par le responsable métier.", encoding="utf-8")
            store = EvidenceStore(root / "evidence.db")
            store.ingest(policy)
            report = evaluate(store, [{"question": "Qui valide les accès sensibles ?", "must_include": "responsable métier"}])
            self.assertEqual(report["passed"], 1)
            self.assertEqual(report["retrieval_recall"], 1)
            self.assertTrue(report["items"][0]["grounded"])


if __name__ == "__main__":
    unittest.main()
