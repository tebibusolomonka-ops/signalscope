# Current State

Last updated at commit 230. Alembic head: `97ebc65e728c` (Create event clusters).

## Done

- Sources, scheduled network ingestion (RSS, web), file import, blob storage.
- Processing jobs, parsers, document revisions, section-aware chunks.
- Lexical, semantic, hybrid and reranked search; retrieval evaluation command
  with optional quality gates.
- Entity extraction (GLiNER) with queue, worker, API and coverage.
- Event and claim extraction (GLiNER2) with queues, workers, APIs and coverage.
- Orphaned event cleanup after chunk replacement and document deletion.
- Exact event linking (`EventLinkingService`) into event clusters, and the
  timeline API over clusters.
- Source provenance profile (counts and dates, no score).
- Research context and citation-checked research answers, with an optional
  local Qwen answer model and a smoke check command.

## Models and providers

| Use | Provider / model | Default |
| --- | --- | --- |
| Embeddings | `sentence_transformers` / `intfloat/multilingual-e5-small` | off |
| Reranking | `sentence_transformers` / mMARCO MiniLM cross-encoder | off |
| Entities | `gliner` / `urchade/gliner_multi-v2.1` | off |
| Events, claims | `gliner2` / `fastino/gliner2.5-multi-v1` | off |
| Answers | `transformers` / `Qwen/Qwen3-4B-Instruct-2507` | off |

Details: [[06 Search and AI]]. Open problems: [[08 Known Issues]].
