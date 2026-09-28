# Architecture

One Python package, `src/signalscope`, with one PostgreSQL database. See
[[07 Decisions]] for why it is built this way.

## Layers

- **API** (`api/`): FastAPI app, routes, error handlers, request ID and logging
  middleware. Routes stay thin and call services. Model registries live on
  `app.state` and are built from settings at startup without loading models.
  Route list: [[04 API Map]].
- **Command line** (`cli.py`): ingestion, imports, backlogs, workers, model
  smoke checks and retrieval evaluation.
- **Domain and services** (`domain/`): one folder per area (sources, documents,
  ingestion, processing, search, entities, events, claims, blobs). Services own
  transactions. Repositories never commit.
- **PostgreSQL**: all state, including job queues and vectors (pgvector). Schema
  changes go through Alembic. See [[03 Database and Migrations]].
- **Blob store** (`storage/`): raw file bytes on the local disk, addressed by
  key. Database rows are written first; failed blob deletes are tracked as
  cleanup tasks.
- **Queues and workers** (`workers/` plus each area's job tables): PostgreSQL
  jobs with leases. See [[05 Workers and Queues]].
- **Parsers** (`parsing/`): text, JSON, HTML, PDF and DOCX, chosen by content
  type through a registry.
- **Search** (`domain/search/`, `embeddings/`, `reranking/`): lexical, semantic,
  hybrid and reranked search. See [[06 Search and AI]].
- **Extraction** (`entities/`, `extraction/`, `events/`, `claims/`): provider
  protocols, registries and local model wrappers. Every provider result goes
  through a shared validation function before it is stored.
- **Research** (`research/`): evidence retrieval, numbered context, answer
  generation behind a protocol, and citation validation. Research sessions
  (`domain/research/`) save each turn with the evidence it was answered from.
- **Investigations** (`domain/investigations/`): saved collections of
  references to records, each with a snapshot taken when it was saved.
- **Dashboard** (`dashboard/`): aggregate counts and zero-filled UTC daily
  series, built with SQL aggregates.
- **Relations** (`relations/`): relation extraction interface and an
  experimental GLiNER2 provider, used only by evaluation. Nothing is stored.
- **Evaluation** (`evaluation/`): retrieval evaluation, and event, claim and
  relation extraction evaluation (`evaluation/extraction/`), against local
  datasets.

## Patterns

- Optional libraries are imported inside a loader, so SignalScope runs without
  them. A missing library becomes a clear 503 or command error.
- Models load lazily behind an asyncio lock and run in a worker thread.
- A provider is chosen by (provider name, model name) from an explicit registry.
  A missing provider is a service-unavailable error.
- Workers commit the job claim before the model runs, so no transaction is open
  during inference.
