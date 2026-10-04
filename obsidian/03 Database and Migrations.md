# Database and Migrations

PostgreSQL 17 with the pgvector extension. Current Alembic head:
`d5b2f3c6a7e1` (Add evaluation report records).

## Rules

- Every schema change is a new Alembic revision. Old migrations are never
  edited. There must be one head (`scripts/check.py` checks it).
- A CI test compares the models with the migrated schema, so both must agree.
- Constraint names follow the naming convention in `db/base.py`.
- IDs are UUIDs. `created_at` and `updated_at` are set by PostgreSQL.

## Tables by area

- **Sources and ingestion**: `sources` (nullable `organization_id`: the root
  of content ownership; NULL means legacy content; no uniqueness on name or
  URL, so organizations can share a feed), `ingestion_runs`, `ingestion_jobs`.
  Documents, chunks and extracted rows have no organization column: they
  belong to their source's organization.
- **Documents**: `documents`, `document_assets` (blob keys),
  `document_extractions`, `document_revisions`, `document_chunks` (with a
  full-text index).
- **Processing and blobs**: `document_processing_jobs`, `blob_cleanup_tasks`.
- **Search**: `chunk_embeddings` (pgvector, HNSW index for the E5 model),
  `embedding_jobs`.
- **Entities**: `entities`, `entity_mentions`, `entity_extraction_jobs`.
- **Events** (event clusters have a nullable `organization_id`; the
  migration only filled it for clusters whose evidence all came from one
  organization): `events`, `event_evidence`, `event_extraction_jobs`,
  `event_clusters`, `event_cluster_members` (event ID is the key, so one
  cluster per event).
- **Claims**: `claims` (unique on normalized text and type), `claim_evidence`
  (exact offsets into the chunk), `claim_extraction_jobs`.
- **Research**: `research_sessions` (mode as text with a check, optional
  source, nullable `organization_id`: sessions search many documents, so they
  belong to an organization themselves; NULL is a legacy session), `research_turns` (unique sequence per session, JSONB citation IDs
  and evidence snapshot, no `updated_at` because turns are history).
- **Investigations**: `investigations` (status `open` or `closed` as text with
  a check; nullable `organization_id` and `created_by_user_id`, both NULL for
  legacy investigations), `investigation_collaborators` (one role per user and
  investigation: owner, editor or viewer), `investigation_items` (item type as text with a check,
  `reference_id` without a foreign key, JSONB snapshot, unique per
  investigation, type and reference).

- **Users**: `users` (unique normalized email, active and system admin flags),
  `user_password_credentials` (one Argon2id hash per user), `user_sessions`
  (SHA-256 token hash only, expiry, revoked time).
- **Organizations**: `organizations` (unique slug, creator), and
  `organization_memberships` (one role per user and organization, role as
  text with a check). `organization_exports` records each requested portable
  export, its lifecycle, format version, expiry and safe BlobStore artifact
  metadata; rows are deleted with the organization.
- **Invitations**: `organization_invitations` (normalized email, role
  admin, member or viewer, never owner; the SHA-256 of the token, unique;
  expiry, accepted and revoked times, inviter). Status is computed from the
  times, not stored. No uniqueness on email, so old rows stay as history.
  The service allows one pending invitation per organization and email,
  checked under a lock on the organization row.
  `cleanup-organization-invitations` deletes invitations accepted, revoked or
  expired more than `SIGNALSCOPE_ORGANIZATION_INVITATION_RETENTION_DAYS` days
  ago, at most `--limit` per run.
- **Audit**: `security_audit_events` (actor, organization, action, resource
  type and ID, JSONB `metadata` object, `created_at` only, since events are
  history). Indexed by time, actor, organization and action.
  `organization_retention_policies` has one row per organization (primary
  key `organization_id`, deleted with the organization) and a nullable
  `security_audit_days` checked to be 30 to 3650. No row, or NULL, means
  events are kept indefinitely.

- **Operations**: `operation_attempts` records each tenant-owned worker claim
  for the six content queues, including its attempt number, safe resource ID,
  start and finish times, outcome and sanitized error. Job and resource IDs
  are not foreign keys, so history survives queue and content deletion. Lease
  tokens, tracebacks, prompts and content are not stored.

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
- Deleting an organization deletes its memberships and invitations, but is
  refused while it has investigations or sources. Deleting a user is refused while they
  invited someone.
- Deleting a user or organization keeps its audit events and sets their
  reference to NULL.
- `cleanup-auth-sessions` deletes sessions that expired or were revoked more
  than `SIGNALSCOPE_AUTH_SESSION_RETENTION_DAYS` days ago, at most `--limit`
  per run.
- Deleting an investigation deletes its items and collaborators, never the
  saved records. Deleting a user is refused while they created an
  investigation or collaborate on one.
  Deleting a saved record leaves the item and its snapshot in place.

See [[05 Workers and Queues]] for the job tables.
