"""Small, deterministic evaluation harness for Evidence Desk retrieval and grounding."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .rag import answer, retrieve
from .store import EvidenceStore


def load_cases(path: Path) -> list[dict[str, str]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("evaluation file must contain a list")
    cases: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict) or not all(isinstance(item.get(key), str) for key in ("question", "must_include")):
            raise ValueError("each evaluation case requires question and must_include strings")
        cases.append({"question": item["question"], "must_include": item["must_include"]})
    return cases


def evaluate(store: EvidenceStore, cases: list[dict[str, str]]) -> dict[str, Any]:
    """Measure whether expected evidence is retrieved and retained in the answer."""
    results: list[dict[str, object]] = []
    for case in cases:
        expected = case["must_include"].lower()
        evidence = retrieve(store, case["question"], limit=4)
        response = answer(store, case["question"])
        retrieved = any(expected in item.text.lower() for item in evidence)
        grounded = expected in str(response["answer"]).lower()
        cited = bool(response["sources"])
        results.append(
            {
                "question": case["question"],
                "retrieved": retrieved,
                "grounded": grounded,
                "cited": cited,
                "passed": retrieved and grounded and cited,
            }
        )

    total = len(results)
    passed = sum(bool(item["passed"]) for item in results)
    return {
        "suite": "golden.v1",
        "total": total,
        "passed": passed,
        "retrieval_recall": round(sum(bool(item["retrieved"]) for item in results) / total, 2) if total else 0,
        "grounded_answer_rate": round(sum(bool(item["grounded"]) for item in results) / total, 2) if total else 0,
        "citation_rate": round(sum(bool(item["cited"]) for item in results) / total, 2) if total else 0,
        "items": results,
    }
