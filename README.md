# Evidence Desk

Evidence Desk is a local-first, auditable RAG workspace for policy, procedure and regulatory documents. It is deliberately built around a question that matters in organisations: **what is the source behind this answer?**

## What it demonstrates

- document ingestion with duplicate detection and version hashes;
- deterministic chunking and a SQLite FTS5 search index;
- hybrid retrieval: lexical search plus token-overlap reranking;
- grounded answers with inline source references and confidence signals;
- an optional LLM adapter, while keeping a working no-key local mode;
- a small evaluation set and automated tests.

## Run it

```bash
cd evidence-desk
PYTHONPATH=src python -m evidence_desk.server
```

Open `http://localhost:8080`. The demo policies are indexed automatically on first run.

## Use it

1. Ask a question such as `Quand faut-il faire valider une demande d'accès ?`.
2. Inspect the answer's source cards and confidence label.
3. Drop `.txt`, `.md` or `.html` files into `data/demo/`, then restart the app.

The application is intentionally local-first. A future production deployment would replace SQLite with Postgres + pgvector/Qdrant, add identity management, asynchronous ingestion and a formal evaluation pipeline.

### Optional LLM mode

The default local mode produces an extractive, grounded synthesis. To connect an approved OpenAI-compatible provider, configure `LLM_ENDPOINT`, `LLM_API_KEY` and `LLM_MODEL`. Only retrieved passages are sent to that provider; if it is unavailable, Evidence Desk falls back to its local evidence-first answer.

## API

- `GET /api/health`
- `GET /api/documents`
- `POST /api/query` with `{ "question": "..." }`
- `POST /api/ingest` with `{ "path": "data/demo/my-file.md" }`

## Project framing for an interview

This is a personal product project, not a client delivery. The interesting discussion is not “I made a chatbot”; it is how to make answers traceable, what happens when retrieval is weak, how versions are handled, and how you would evaluate the system before people rely on it.
