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
- `POST /sources/compare`: 2 to 10 sources side by side, with shared clusters,
  entities and claims; no score or ranking
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
- `GET /events/{id}/link-suggestions`: advisory similar events (E5); changes
  nothing; 503 without local embeddings
- `GET /claims`, `GET /claims/coverage`, `GET /claims/{id}`

## Timeline

- `GET /timeline`: event clusters in time order, with event, source and
  evidence counts.
- `GET /event-clusters/{id}`: one cluster with its members and their evidence
  (no document text). There is no merge or split route.

## Research

- `POST /research/context`: numbered evidence, no answer.
- `POST /research/answer`: answer with checked citations. 503 unless local
  answers are enabled.
- `POST /research/sessions`, `GET /research/sessions/{id}`
- `GET /research/sessions/{id}/turns`, `POST /research/sessions/{id}/turns`:
  each turn has its question, answer (or null without a model), citations and
  evidence summaries. Prompts and chunk text are not returned.
- `GET /research/sessions/{id}/export?format=json|markdown`: every turn with
  its saved evidence; never searches again.

## Investigations

Global until users exist: everyone who can reach the API sees all of them.

- `POST /investigations`, `GET /investigations` (`status` filter, paged),
  `GET /investigations/{id}`, `PATCH /investigations/{id}`,
  `DELETE /investigations/{id}`
- `POST /investigations/{id}/items`, `GET /investigations/{id}/items`,
  `DELETE /investigations/{id}/items/{item_id}`
- `POST /investigations/{id}/research-sessions/{session_id}`: save a session
  once (201 new, 200 already saved)
- `GET /investigations/{id}/export?format=json|markdown`: saved snapshots
  grouped by type, with whether each record still exists.
- A closed investigation answers 409 to changes until it is reopened.

## Dashboard

Aggregates only; no record lists, scores or rankings.

- `GET /dashboard/overview`: record counts and waiting or running jobs
- `GET /dashboard/sources?days=&source_id=`: documents stored and published
  per UTC day
- `GET /dashboard/events?days=&event_type=&source_id=`: events, clusters and
  cross-source clusters per UTC day
- `days` is 1 to 365; every day is listed.

## Not in the API

Relation extraction and extraction evaluation are command line only
(`signalscope evaluate-extraction`, `signalscope check-structured-model`).
Investigations can also be exported with `signalscope export-investigation`.
There is no relation route, because no relations are stored.

See [[06 Search and AI]] for the models behind these routes.
