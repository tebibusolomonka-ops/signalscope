# Current State

Last updated at commit 273. Batch 251 to 270 ended at commit 272 (`40f2d5c`),
with two corrective commits. Alembic head: `ca4da746adef` (Create investigation items).

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
  similarity), exposed read-only at `GET /events/{id}/link-suggestions`. They
  never change clusters.
- Event cluster detail (`EventClusterDetailService`,
  `GET /event-clusters/{id}`): members and where each was reported. Read only.
- Source comparison service (`SourceComparisonService`): 2 to 10 sources side
  by side with provenance counts, plus shared clusters, entities and claims.
  Exposed as `POST /sources/compare`.
- Saved investigations (`/investigations`): open or closed, with items that
  reference sources, documents, events, clusters, entities, claims and
  research sessions, each with a snapshot. Global, no owner.
- Exports as JSON or Markdown: research sessions
  (`GET /research/sessions/{id}/export`, from each turn's saved evidence) and
  investigations (`GET /investigations/{id}/export`, from saved snapshots,
  grouped by type), plus `signalscope export-investigation` with `--output`
  and `--overwrite`. Nothing is written on the server.
- Dashboard aggregates (`/dashboard/overview`, `/dashboard/sources`,
  `/dashboard/events`): record counts, open jobs, and daily source and event
  activity. Counts only.
- Knowledge-graph edges are not stored. The relation provider is an evaluated
  candidate only, and no real benchmark has been run.
- Multi-turn research sessions: sessions and turns in the database, a service
  and routes under `/research/sessions`. Earlier turns are context for the
  answer model, never evidence.
- Source provenance profile (counts and dates, no score).
- Research context and citation-checked research answers, with an optional
  local Qwen answer model and a smoke check command.
- Extraction evaluation (`evaluation/extraction/`): a JSON dataset with gold
  events, claims and relations, exact one-to-one matching, and precision,
  recall and F1. `signalscope evaluate-extraction` runs it with the local
  GLiNER2 model (`--mode`, `--json-output`, and user-defined
  `--quality-gates`). No built-in targets.
- `signalscope check-structured-model` loads the real GLiNER2 model and runs
  one structured and one relation extraction (developer use; may download).
- Relation extraction interface (`relations/`) and an experimental GLiNER2
  relation provider. Evaluation only: no worker, no table, no graph.
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
| Relations (evaluation only) | `gliner2` / `fastino/gliner2.5-multi-v1` | off |
| Answers | `transformers` / `Qwen/Qwen3-4B-Instruct-2507` | off |

Details: [[06 Search and AI]]. Open problems: [[08 Known Issues]].
