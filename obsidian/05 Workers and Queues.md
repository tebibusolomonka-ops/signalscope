# Workers and Queues

Queues are PostgreSQL tables. There is no Redis, Celery or Kafka; see
[[07 Decisions]].

## Queues

| Queue | Job table | Worker command | Backlog command |
| --- | --- | --- | --- |
| Ingestion | `ingestion_jobs` | `run-worker` | `schedule-ingestion` |
| Processing | `document_processing_jobs` | `run-processing-worker` | (queued on import) |
| Embedding | `embedding_jobs` | `run-embedding-worker` | `queue-embeddings` |
| Entities | `entity_extraction_jobs` | `run-entity-worker` | `queue-entities` |
| Events | `event_extraction_jobs` | `run-event-worker` | `queue-events` |
| Claims | `claim_extraction_jobs` | `run-claim-worker` | `queue-claims` |
| Blob cleanup | `blob_cleanup_tasks` | `cleanup-blobs` | (added on failed deletes) |

## How a job runs

- **Claim**: `SELECT ... FOR UPDATE SKIP LOCKED`, so workers never take the
  same job. Each claim sets a new `lease_token` and a lease expiry.
- **Commit before work**: the claim is committed before the model or network
  call, so no transaction or row lock is held during slow work.
- **Heartbeat**: `keep_lease_alive` extends the lease while the job runs. It
  needs the token.
- **Finish**: the job row is locked and the status and token are checked. A
  worker that lost its lease saves nothing (`lease_lost`).
- **Recovery**: workers put stale running jobs back in the queue before each
  claim, which clears the token.
- **Loop**: `WorkerLoop` supports `--once`, `--poll-seconds` and `--max-jobs`,
  and stops after the current job on Ctrl+C or SIGTERM.

## Backlogs

Backlog commands walk chunks in (document, position) order with keyset paging,
one bounded transaction per page. They never load a model. A chunk counts as
already read when it has results or a completed job.

## Extraction workers

A rerun of a chunk replaces that model's results for the chunk. The event
worker links its new events into clusters after the job is committed; a
linking failure is logged and the events stay unclustered for
`link-events` to repair. Model errors
are stored as safe messages. Unknown errors never store private details.
