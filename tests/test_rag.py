import json
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
            self.assertEqual(result["state"], "grounded")
            self.assertTrue(result["sources"][0]["citation"])
            self.assertTrue(result["sources"][0]["content_fingerprint"].startswith("sha256:"))
            self.assertEqual(result["receipt"]["state"], "grounded")

    def test_ingestion_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "policy.md"
            source.write_text("Une politique de test avec suffisamment de contenu.", encoding="utf-8")
            store = EvidenceStore(root / "evidence.db")
            self.assertEqual(store.ingest(source)["status"], "indexed")
            self.assertEqual(store.ingest(source)["status"], "unchanged")

    def test_versioned_source_metadata_is_exposed_at_passage_level(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = root / "access.md"
            policy.write_text("Les accès privilégiés nécessitent une validation documentée.", encoding="utf-8")
            store = EvidenceStore(root / "evidence.db")
            store.ingest(
                policy,
                metadata={
                    "source_id": "POL-ACCESS-007",
                    "version": "4.2",
                    "authority": "controlled",
                    "owner": "Security Operations",
                    "reviewed_at": "2026-01-05",
                    "review_due_at": "2027-01-05",
                },
            )
            result = answer(store, "Quelle validation est nécessaire pour les accès privilégiés ?")
            source = result["sources"][0]
            self.assertEqual(source["source_id"], "POL-ACCESS-007")
            self.assertEqual(source["version"], "4.2")
            self.assertEqual(source["authority"], "controlled")
            self.assertEqual(source["freshness"]["state"], "current")
            self.assertIn("POL-ACCESS-007@4.2#p1", source["citation"])

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

    def test_superseded_sources_are_not_used_to_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = root / "retired.md"
            policy.write_text("Le seuil obsolète est de trois heures.", encoding="utf-8")
            store = EvidenceStore(root / "evidence.db")
            store.ingest(policy, metadata={"status": "superseded"})
            result = answer(store, "Quel est le seuil obsolète ?")
            self.assertEqual(result["state"], "insufficient_evidence")
            self.assertFalse(result["sources"])

    def test_new_active_version_supersedes_an_older_version_of_the_same_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "policy-v1.md"
            current = root / "policy-v2.md"
            old.write_text("Le délai de validation est de trois jours ouvrés.", encoding="utf-8")
            current.write_text("Le délai de validation est de cinq jours ouvrés.", encoding="utf-8")
            store = EvidenceStore(root / "evidence.db")
            store.ingest(old, metadata={"source_id": "POL-DELAY-001", "version": "1.0", "authority": "controlled"})
            store.ingest(current, metadata={"source_id": "POL-DELAY-001", "version": "2.0", "authority": "controlled"})
            result = answer(store, "Quel est le délai de validation ?")
            self.assertIn("cinq jours", result["answer"])
            self.assertNotIn("trois jours", result["answer"])
            documents = store.list_documents()
            self.assertEqual({item["status"] for item in documents}, {"active", "superseded"})

    def test_controlled_source_is_preferred_when_coverage_is_equal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.md"
            controlled = root / "controlled.md"
            reference.write_text("La publication requiert une validation du responsable métier.", encoding="utf-8")
            controlled.write_text("La publication requiert une validation du responsable métier.", encoding="utf-8")
            store = EvidenceStore(root / "evidence.db")
            store.ingest(reference, metadata={"source_id": "REF-001", "authority": "reference"})
            store.ingest(controlled, metadata={"source_id": "POL-001", "authority": "controlled"})
            result = answer(store, "Qui valide la publication ?")
            self.assertEqual(result["sources"][0]["source_id"], "POL-001")

    def test_weak_overlap_does_not_turn_an_incidental_source_into_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            access = root / "access.md"
            incident = root / "incident.md"
            access.write_text("Les accès à une donnée sensible sont validés par le responsable métier.", encoding="utf-8")
            incident.write_text("Un incident est ouvert lorsqu'une donnée sensible est exposée.", encoding="utf-8")
            store = EvidenceStore(root / "evidence.db")
            store.ingest(access, metadata={"source_id": "POL-ACCESS-001", "authority": "controlled"})
            store.ingest(incident, metadata={"source_id": "RUN-INC-002", "authority": "controlled"})
            result = answer(store, "Qui valide un accès à une donnée sensible ?")
            self.assertEqual([source["source_id"] for source in result["sources"]], ["POL-ACCESS-001"])
            self.assertNotIn("incident est ouvert", result["answer"].lower())

    def test_invalid_metadata_date_is_rejected_before_indexing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = root / "access.md"
            policy.write_text("Les accès sensibles doivent être documentés.", encoding="utf-8")
            store = EvidenceStore(root / "evidence.db")
            with self.assertRaises(ValueError):
                store.ingest(policy, metadata={"review_due_at": "2026-02-30"})

    def test_insufficient_evidence_refuses_and_records_a_privacy_safe_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = root / "access.md"
            policy.write_text("Les accès sensibles doivent être documentés.", encoding="utf-8")
            store = EvidenceStore(root / "evidence.db")
            store.ingest(policy)
            question = "Quel protocole protège les clés cryptographiques ?"
            result = answer(store, question)
            self.assertEqual(result["state"], "insufficient_evidence")
            self.assertFalse(result["retrieval"]["safe_to_answer"])
            receipt = store.list_receipts()[0]
            self.assertEqual(receipt["id"], result["receipt"]["id"])
            self.assertNotIn(question, json.dumps(receipt, ensure_ascii=False))
            self.assertEqual(receipt["retrieved_passages"], 0)

    def test_evaluation_separates_retrieval_grounding_traceability_and_abstention(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = root / "access.md"
            policy.write_text("Les accès sensibles sont validés par le responsable métier.", encoding="utf-8")
            store = EvidenceStore(root / "evidence.db")
            store.ingest(policy, metadata={"source_id": "POL-ACCESS-001", "version": "1.0"})
            report = evaluate(
                store,
                [
                    {
                        "question": "Qui valide les accès sensibles ?",
                        "must_include": "responsable métier",
                        "expected_sources": ["POL-ACCESS-001"],
                        "expect_abstention": False,
                    },
                    {
                        "question": "Quel protocole protège les clés cryptographiques ?",
                        "must_include": "",
                        "expected_sources": [],
                        "expect_abstention": True,
                    },
                ],
            )
            self.assertEqual(report["suite"], "golden.v2")
            self.assertEqual(report["passed"], 2)
            self.assertEqual(report["retrieval_recall"], 1)
            self.assertEqual(report["safe_abstention_rate"], 1)
            self.assertTrue(report["items"][0]["traceable"])


if __name__ == "__main__":
    unittest.main()
