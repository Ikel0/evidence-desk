from __future__ import annotations

import json
import math
import os
import re
from datetime import date
from urllib.request import Request, urlopen

from .store import Evidence, EvidenceStore


STOPWORDS = {
    "avec", "dans", "pour", "quel", "quelle", "quels", "quelles", "sont", "être", "fait", "faire",
    "faut", "qui", "que", "les", "des", "une", "un", "est", "sur", "par", "aux", "ses", "ces",
}

AUTHORITY_RANK = {"authoritative": 3, "controlled": 2, "reference": 1, "unclassified": 0}


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-zà-ÿ0-9]{3,}", value.lower()) if token not in STOPWORDS}


def retrieve(store: EvidenceStore, question: str, limit: int = 4) -> list[Evidence]:
    """Retrieve active passages, then reject weak lexical coincidences.

    FTS can legitimately return a passage that shares one generic word with a
    question. A source only enters the answer path if it covers enough of the
    question and stays close to the best candidate for that query.
    """
    question_tokens = _tokens(question)
    evidence = store.search(question, limit=12)
    scored = [
        (item, len(question_tokens & _tokens(item.text)))
        for item in evidence
    ]
    ranked = sorted(
        scored,
        key=lambda entry: (
            entry[1] * 10,
            AUTHORITY_RANK.get(entry[0].authority, 0),
            -entry[0].lexical_score,
        ),
        reverse=True,
    )
    if not ranked:
        return []
    best_overlap = ranked[0][1]
    absolute_floor = max(1, min(2, math.ceil(len(question_tokens) * 0.4)))
    relative_floor = max(1, math.ceil(best_overlap * 0.7))
    required_overlap = max(absolute_floor, relative_floor)
    return [item for item, overlap in ranked if overlap >= required_overlap][:limit]


def _best_sentences(evidence: list[Evidence], question: str) -> list[tuple[str, Evidence]]:
    tokens = _tokens(question)
    candidates: list[tuple[int, str, Evidence]] = []
    seen: set[str] = set()
    for item in evidence:
        for sentence in re.split(r"(?<=[.!?])\s+", item.text):
            clean = sentence.strip()
            score = len(tokens & _tokens(clean))
            key = clean.lower()
            if score and key not in seen:
                candidates.append((score, clean, item))
                seen.add(key)
    candidates.sort(key=lambda value: value[0], reverse=True)
    if not candidates:
        return []
    highest_overlap = candidates[0][0]
    required_overlap = max(1, min(2, highest_overlap))
    return [
        (sentence, item)
        for score, sentence, item in candidates
        if score >= required_overlap
    ][:3]


def _generate_with_llm(question: str, evidence: list[Evidence]) -> tuple[str | None, str]:
    """Use an explicit provider only with retrieved passages and a strict citation rule."""
    endpoint = os.getenv("LLM_ENDPOINT")
    api_key = os.getenv("LLM_API_KEY")
    model = os.getenv("LLM_MODEL")
    if not all((endpoint, api_key, model)):
        return None, "not_configured"
    context = "\n\n".join(f"[S{index + 1}] {item.text}" for index, item in enumerate(evidence))
    prompt = (
        "Tu es un assistant documentaire. Réponds uniquement à partir des extraits fournis. "
        "Chaque phrase factuelle doit finir par une ou plusieurs citations [S1], [S2], etc. "
        "Si les preuves sont insuffisantes, réponds exactement: PREUVES_INSUFFISANTES. "
        "N'ajoute aucune information externe. Rédige une réponse concise en français.\n\n"
        f"Question : {question}\n\nExtraits :\n{context}"
    )
    body = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0},
    ).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read())
        return str(payload["choices"][0]["message"]["content"]).strip(), "received"
    except Exception:
        # The local extractive path remains available when a configured provider fails.
        return None, "provider_unavailable"


def _cited_llm_answer(value: str | None, source_count: int) -> bool:
    if not value or value == "PREUVES_INSUFFISANTES":
        return False
    allowed = {f"S{index}" for index in range(1, source_count + 1)}
    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", value) if item.strip()]
    if not sentences:
        return False
    for sentence in sentences:
        citations = set(re.findall(r"\[(S\d+)\]", sentence))
        if not citations or not citations.issubset(allowed):
            return False
    return True


def _freshness(review_due_at: str | None) -> dict[str, str]:
    if not review_due_at:
        return {"state": "unknown", "label": "date de revue non renseignée"}
    try:
        due = date.fromisoformat(review_due_at)
    except ValueError:
        return {"state": "unknown", "label": "date de revue invalide"}
    days = (due - date.today()).days
    if days < 0:
        return {"state": "review_overdue", "label": "revue échue"}
    if days <= 30:
        return {"state": "review_soon", "label": "revue proche"}
    return {"state": "current", "label": "revue à jour"}


def _source_payload(item: Evidence, index: int) -> dict[str, object]:
    freshness = _freshness(item.review_due_at)
    return {
        "id": f"S{index}",
        "citation": f"{item.source_id}@{item.version}#p{item.position}",
        "source_id": item.source_id,
        "document": item.document,
        "version": item.version,
        "authority": item.authority,
        "status": item.status,
        "owner": item.owner,
        "reviewed_at": item.reviewed_at,
        "review_due_at": item.review_due_at,
        "freshness": freshness,
        "content_fingerprint": f"sha256:{item.content_hash[:16]}",
        "chunk_id": item.chunk_id,
        "position": item.position,
        "excerpt": item.text[:360] + ("…" if len(item.text) > 360 else ""),
    }


def _retrieval_summary(question: str, evidence: list[Evidence]) -> dict[str, object]:
    question_tokens = _tokens(question)
    covered = set().union(*(_tokens(item.text) for item in evidence)) & question_tokens if evidence else set()
    coverage = round(len(covered) / len(question_tokens), 2) if question_tokens else 0.0
    return {
        "candidates": len(evidence),
        "returned": len(evidence),
        "query_terms": len(question_tokens),
        "term_coverage": coverage,
        "strategy": "FTS5 + reranking par recouvrement lexical",
        "active_source_filter": True,
        "authority_preference": "authoritative > controlled > reference > unclassified",
    }


def answer(store: EvidenceStore, question: str) -> dict[str, object]:
    """Return a cited answer or a deliberate refusal when no evidence was found."""
    normalized_question = question.strip()
    evidence = retrieve(store, normalized_question)
    retrieval = _retrieval_summary(normalized_question, evidence)
    if not evidence:
        receipt = store.record_receipt(
            normalized_question,
            [],
            response_state="insufficient_evidence",
            generation="none",
            reason="no_active_passage_retrieved",
        )
        retrieval.update(
            {
                "safe_to_answer": False,
                "reason": "Aucun passage actif ne soutient cette question dans le corpus actuel.",
            }
        )
        return {
            "state": "insufficient_evidence",
            "answer": "Je ne peux pas répondre de façon fiable avec le corpus actuellement indexé. Reformulez la question ou ajoutez une source contrôlée.",
            "confidence": "insuffisante",
            "sources": [],
            "retrieval": retrieval,
            "generation": "none",
            "receipt": receipt,
        }

    sources = [_source_payload(item, index + 1) for index, item in enumerate(evidence)]
    generated, generation_status = _generate_with_llm(normalized_question, evidence)
    if _cited_llm_answer(generated, len(sources)):
        synthesis = generated
        generation = "llm_cited"
        generation_reason = "provider_output_passed_citation_check"
    else:
        citations = {item.chunk_id: f"S{index + 1}" for index, item in enumerate(evidence)}
        sentences = _best_sentences(evidence, normalized_question)
        synthesis = " ".join(f"{sentence} [{citations[item.chunk_id]}]" for sentence, item in sentences)
        generation = "extractive"
        generation_reason = "local_extractive" if generation_status == "not_configured" else f"fallback_{generation_status}"

    has_review_warning = any(source["freshness"]["state"] == "review_overdue" for source in sources)
    state = "grounded_with_review_warning" if has_review_warning else "grounded"
    confidence = "modérée" if has_review_warning or len(evidence) < 3 else "élevée"
    retrieval.update({"safe_to_answer": True, "reason": "Passages actifs récupérés et cités."})
    receipt = store.record_receipt(
        normalized_question,
        evidence,
        response_state=state,
        generation=generation,
        reason=generation_reason,
    )
    return {
        "state": state,
        "answer": f"D’après les passages récupérés : {synthesis}",
        "confidence": confidence,
        "sources": sources,
        "retrieval": retrieval,
        "generation": generation,
        "receipt": receipt,
    }
