# Database and Migrations

PostgreSQL 17 with the pgvector extension. Current Alembic head:
`97ebc65e728c` (Create event clusters).

## Rules

- Every schema change is a new Alembic revision. Old migrations are never
  edited. There must be one head (`scripts/check.py` checks it).
- A CI test compares the models with the migrated schema, so both must agree.
- Constraint names follow the naming convention in `db/base.py`.
- IDs are UUIDs. `created_at` and `updated_at` are set by PostgreSQL.

## Tables by area

- **Sources and ingestion**: `sources`, `ingestion_runs`, `ingestion_jobs`.
- **Documents**: `documents`, `document_assets` (blob keys),
  `document_extractions`, `document_revisions`, `document_chunks` (with a
  full-text index).
- **Processing and blobs**: `document_processing_jobs`, `blob_cleanup_tasks`.
- **Search**: `chunk_embeddings` (pgvector, HNSW index for the E5 model),
  `embedding_jobs`.
- **Entities**: `entities`, `entity_mentions`, `entity_extraction_jobs`.
- **Events**: `events`, `event_evidence`, `event_extraction_jobs`,
  `event_clusters`, `event_cluster_members` (event ID is the key, so one
  cluster per event).
- **Claims**: `claims` (unique on normalized text and type), `claim_evidence`
  (exact offsets into the chunk), `claim_extraction_jobs`.

## Deletion behavior

- Deleting a chunk deletes its embeddings, mentions, evidence and jobs.
- The database keeps an event when its evidence goes; code then deletes
  events left with no evidence.
- Claims with evidence cannot be deleted. Sources with documents cannot be
  deleted.

See [[05 Workers and Queues]] for the job tables.
