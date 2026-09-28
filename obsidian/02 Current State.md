# Current State

Last updated at commit 244. Alembic head: `09376fcf43b6` (Create research turns).

## Done

- Sources, scheduled network ingestion (RSS, web), file import, blob storage.
- Processing jobs, parsers, document revisions, section-aware chunks.
- Lexical, semantic, hybrid and reranked search; retrieval evaluation command
  with optional quality gates.
- Entity extraction (GLiNER) with queue, worker, API and coverage.
- Event and claim extraction (GLiNER2) with queues, workers, APIs and coverage.
- Orphaned event cleanup after chunk replacement and document deletion.
- Exact event linking (`EventLinkingService`) into event clusters, and the
  timeline API over clusters. The event worker links new events right after
  it commits them; `signalscope link-events` links any left over.
- Empty event clusters are deleted whenever orphaned events are deleted
  (reprocessing, document deletion, worker reruns).
- Semantic event link suggestions (`EventLinkSuggestionService`, E5 cosine
  similarity). Code only, no route yet. They never change clusters.
- Source comparison service (`SourceComparisonService`): 2 to 10 sources side
  by side with provenance counts, plus shared clusters, entities and claims.
  Exposed as `POST /sources/compare`.
- Multi-turn research sessions: sessions and turns in the database, a service
  and routes under `/research/sessions`. Earlier turns are context for the
  answer model, never evidence.
- Source provenance profile (counts and dates, no score).
- Research context and citation-checked research answers, with an optional
  local Qwen answer model and a smoke check command.
- Extraction evaluation in code (`evaluation/extraction/`): a dataset type
  with gold events and claims, and precision, recall and F1 for any event or
  claim provider. No command runs it yet.
- The GLiNER2 loader matches gliner2 2.0: only `map_location` is passed, and a
  cache folder is filled with `huggingface_hub.snapshot_download` first.
- This vault (`obsidian/`).

## Models and providers

| Use | Provider / model | Default |
| --- | --- | --- |
| Embeddings | `sentence_transformers` / `intfloat/multilingual-e5-small` | off |
| Reranking | `sentence_transformers` / mMARCO MiniLM cross-encoder | off |
| Entities | `gliner` / `urchade/gliner_multi-v2.1` | off |
| Events, claims | `gliner2` / `fastino/gliner2.5-multi-v1` | off |
| Answers | `transformers` / `Qwen/Qwen3-4B-Instruct-2507` | off |

Details: [[06 Search and AI]]. Open problems: [[08 Known Issues]].
