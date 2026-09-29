# Database and Migrations

PostgreSQL 17 with the pgvector extension. Current Alembic head:
`f193df76c881` (Create organization
memberships).

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
- **Research**: `research_sessions` (mode as text with a check, optional
  source), `research_turns` (unique sequence per session, JSONB citation IDs
  and evidence snapshot, no `updated_at` because turns are history).
- **Investigations**: `investigations` (status `open` or `closed` as text with
  a check, no owner), `investigation_items` (item type as text with a check,
  `reference_id` without a foreign key, JSONB snapshot, unique per
  investigation, type and reference).

- **Users**: `users` (unique normalized email, active and system admin flags),
  `user_password_credentials` (one Argon2id hash per user), `user_sessions`
  (SHA-256 token hash only, expiry, revoked time).
- **Organizations**: `organizations` (unique slug, creator), and
  `organization_memberships` (one role per user and organization, role as
  text with a check).

## Deletion behavior

- Deleting a chunk deletes its embeddings, mentions, evidence and jobs.
- The database keeps an event when its evidence goes; code then deletes
  events left with no evidence.
- Claims with evidence cannot be deleted. Sources with documents, ingestion
  runs or research sessions cannot be deleted.
- Deleting a research session deletes its turns.
- Deleting a user deletes their password credential and sessions, but is
  refused while they created an organization or are a member of one. There is
  no user delete API.
- Deleting an organization deletes its memberships.
- Deleting an investigation deletes its items, never the saved records.
  Deleting a saved record leaves the item and its snapshot in place.

See [[05 Workers and Queues]] for the job tables.
