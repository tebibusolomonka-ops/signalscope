# API Map

All routes are JSON over HTTP, without authentication. Routes that need the
database answer 503 when it is not configured. Routes that need an optional
model answer 503 when it is off. Lists are paged with `limit` and `offset`.

## Health

- `GET /health`

## Sources and ingestion

- `POST /sources`, `GET /sources`, `GET /sources/{id}`, `DELETE /sources/{id}`
- `PUT /sources/{id}/schedule`, `DELETE /sources/{id}/schedule`
- `GET /sources/{id}/provenance`: observed counts and dates, no score
- `POST /ingestion-runs`, `GET /ingestion-runs`, `GET /ingestion-runs/{id}`

## Documents

- `POST /documents`, `GET /documents`, `GET /documents/{id}`,
  `DELETE /documents/{id}`
- `GET /documents/{id}/revisions`, `GET /documents/{id}/revisions/{version}`

## Search and embeddings

- `GET /search` (lexical), `GET /search/semantic`, `GET /search/hybrid`,
  `GET /search/reranked`
- `GET /embeddings/coverage`

## Entities, events and claims

All read only. Coverage routes read the database and never load a model.

- `GET /entities`, `GET /entities/coverage`, `GET /entities/{id}`
- `GET /events`, `GET /events/coverage`, `GET /events/{id}`
- `GET /claims`, `GET /claims/coverage`, `GET /claims/{id}`

## Timeline

- `GET /timeline`: event clusters in time order, with event, source and
  evidence counts.

## Research

- `POST /research/context`: numbered evidence, no answer.
- `POST /research/answer`: answer with checked citations. 503 unless local
  answers are enabled.

See [[06 Search and AI]] for the models behind these routes.
