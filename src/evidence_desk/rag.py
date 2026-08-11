from __future__ import annotations

import re
import json
import os
from urllib.request import Request, urlopen

from .store import Evidence, EvidenceStore


STOPWORDS = {"avec", "dans", "pour", "quel", "quelle", "quels", "quelles", "sont", "être", "fait", "faire", "faut", "qui", "que", "les", "des", "une", "un", "est", "sur", "par", "aux", "ses", "ces"}


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-zà-ÿ0-9]{3,}", value.lower()) if token not in STOPWORDS}


def retrieve(store: EvidenceStore, question: str, limit: int = 4) -> list[Evidence]:
    question_tokens = _tokens(question)
    evidence = store.search(question, limit=12)
    ranked = sorted(
        evidence,
        key=lambda item: (len(question_tokens & _tokens(item.text)) * 10, -item.lexical_score),
        reverse=True,
    )
    return ranked[:limit]


def _best_sentences(evidence: list[Evidence], question: str) -> list[str]:
    tokens = _tokens(question)
    candidates: list[tuple[int, str, Evidence]] = []
    for item in evidence:
        for sentence in re.split(r"(?<=[.!?])\s+", item.text):
            score = len(tokens & _tokens(sentence))
            if score:
                candidates.append((score, sentence.strip(), item))
    candidates.sort(key=lambda value: value[0], reverse=True)
    return [sentence for _, sentence, _ in candidates[:3]]


def _generate_with_llm(question: str, evidence: list[Evidence]) -> str | None:
    """Optional adapter for an OpenAI-compatible chat endpoint.

    The core project stays usable without sending documents anywhere. When an
    organisation explicitly configures a provider, this function receives only
    the retrieved passages and is told to refuse unsupported claims.
    """
    endpoint = os.getenv("LLM_ENDPOINT")
    api_key = os.getenv("LLM_API_KEY")
    model = os.getenv("LLM_MODEL")
    if not all((endpoint, api_key, model)):
        return None
    context = "\n\n".join(f"[S{index + 1}] {item.text}" for index, item in enumerate(evidence))
    prompt = (
        "Tu es un assistant documentaire. Réponds uniquement à partir des extraits fournis. "
        "Si les preuves sont insuffisantes, dis-le explicitement. Rédige une réponse concise en français "
        "et cite les identifiants de source entre crochets.\n\n"
        f"Question : {question}\n\nExtraits :\n{context}"
    )
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}).encode("utf-8")
    request = Request(endpoint, data=body, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read())
        return str(payload["choices"][0]["message"]["content"]).strip()
    except Exception:
        # A RAG workspace should remain available if its external LLM is down.
        return None


def answer(store: EvidenceStore, question: str) -> dict[str, object]:
    evidence = retrieve(store, question)
    sources = [
        {
            "id": f"S{index + 1}",
            "document": item.document,
            "version": item.version,
            "position": item.position,
            "excerpt": item.text[:360] + ("…" if len(item.text) > 360 else ""),
        }
        for index, item in enumerate(evidence)
    ]
    if not evidence:
        return {"answer": "Je ne trouve pas de passage suffisamment pertinent dans le corpus actuel.", "confidence": "faible", "sources": []}
    synthesis = _generate_with_llm(question, evidence) or " ".join(_best_sentences(evidence, question))
    confidence = "élevée" if len(evidence) >= 3 else "modérée"
    return {
        "answer": f"D’après les documents indexés : {synthesis}",
        "confidence": confidence,
        "sources": sources,
        "retrieval": {"candidates": len(evidence), "strategy": "FTS5 + reranking par recouvrement lexical"},
        "generation": "llm" if os.getenv("LLM_ENDPOINT") and os.getenv("LLM_API_KEY") and os.getenv("LLM_MODEL") else "extractive",
    }
