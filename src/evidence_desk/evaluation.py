"""Small, deterministic evaluation harness for retrieval, grounding and refusal."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .rag import answer, retrieve
from .store import EvidenceStore


def load_cases(path: Path) -> list[dict[str, object]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("evaluation file must contain a list")
    cases: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("question"), str):
            raise ValueError("each evaluation case requires a question string")
        must_include = item.get("must_include")
        expect_abstention = item.get("expect_abstention", False)
        if not isinstance(expect_abstention, bool):
            raise ValueError("expect_abstention must be a boolean")
        if not expect_abstention and not isinstance(must_include, str):
            raise ValueError("non-abstention cases require a must_include string")
        expected_sources = item.get("expected_sources", [])
        if not isinstance(expected_sources, list) or not all(isinstance(value, str) for value in expected_sources):
            raise ValueError("expected_sources must be a list of strings")
        cases.append(
            {
                "question": item["question"],
                "must_include": must_include if isinstance(must_include, str) else "",
                "expected_sources": expected_sources,
                "expect_abstention": expect_abstention,
            }
        )
    return cases


def _source_traceable(source: dict[str, object]) -> bool:
    freshness = source.get("freshness")
    return bool(
        source.get("citation")
        and source.get("source_id")
        and source.get("version")
        and source.get("content_fingerprint")
        and isinstance(freshness, dict)
        and freshness.get("state")
    )


def evaluate(store: EvidenceStore, cases: list[dict[str, object]]) -> dict[str, Any]:
    """Measure retrieval, grounding, traceability and safe abstention separately."""
    results: list[dict[str, object]] = []
    for case in cases:
        question = str(case["question"])
        expected = str(case["must_include"]).lower()
        expected_sources = set(case["expected_sources"])
        expect_abstention = bool(case["expect_abstention"])
        evidence = retrieve(store, question, limit=4)
        response = answer(store, question)
        sources = list(response["sources"])
        if expect_abstention:
            retrieved = not evidence
            grounded = response["state"] == "insufficient_evidence"
            cited = not sources
            source_match = True
            traceable = bool(response.get("receipt"))
        else:
            retrieved = any(expected in item.text.lower() for item in evidence)
            grounded = expected in str(response["answer"]).lower()
            cited = bool(sources)
            source_match = not expected_sources or expected_sources.issubset({str(source.get("source_id")) for source in sources})
            traceable = bool(sources) and all(_source_traceable(source) for source in sources) and bool(response.get("receipt"))
        results.append(
            {
                "question": question,
                "expected_abstention": expect_abstention,
                "retrieved": retrieved,
                "grounded": grounded,
                "cited": cited,
                "source_match": source_match,
                "traceable": traceable,
                "passed": retrieved and grounded and cited and source_match and traceable,
            }
        )

    total = len(results)
    passed = sum(bool(item["passed"]) for item in results)
    non_abstention = [item for item in results if not item["expected_abstention"]]
    abstentions = [item for item in results if item["expected_abstention"]]
    return {
        "suite": "golden.v2",
        "total": total,
        "passed": passed,
        "retrieval_recall": round(
            sum(bool(item["retrieved"]) for item in non_abstention) / len(non_abstention), 2
        ) if non_abstention else 0,
        "grounded_answer_rate": round(
            sum(bool(item["grounded"]) for item in non_abstention) / len(non_abstention), 2
        ) if non_abstention else 0,
        "citation_rate": round(
            sum(bool(item["cited"]) for item in non_abstention) / len(non_abstention), 2
        ) if non_abstention else 0,
        "traceability_rate": round(
            sum(bool(item["traceable"]) for item in results) / total, 2
        ) if total else 0,
        "safe_abstention_rate": round(
            sum(bool(item["passed"]) for item in abstentions) / len(abstentions), 2
        ) if abstentions else 1,
        "items": results,
    }
