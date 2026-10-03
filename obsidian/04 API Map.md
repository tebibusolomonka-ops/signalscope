# API Map

All routes are JSON over HTTP. With auth off, content routes stay open as
before. With auth on, content routes take `organization_id` for lists and
searches, and check the source's organization for single records (see
[[07 Decisions]]). Every content route is scoped; the sections below say
how. System admins without `organization_id` get legacy content only. Routes that need the
database answer 503 when it is not configured. Routes that need an optional
model answer 503 when it is off. Lists are paged with `limit` and `offset`.

## Authentication

Only when `SIGNALSCOPE_AUTH_ENABLED=true`; otherwise 503. Send the token as
`Authorization: Bearer <token>`.

- `POST /auth/login`: email and password, returns an opaque token once. Every
  failure is the same 401.
- `POST /auth/logout`: revokes the current session.
- `GET /auth/me`: the signed in user.
- `GET /auth/sessions`: my sessions, newest first, with `current_session`;
  never tokens or hashes.
- `DELETE /auth/sessions/{session_id}`: revoke one of mine; someone else's
  gives 404.
- `POST /auth/logout-all`: revoke all of mine, the current one included.
- `POST /auth/change-password`: current and new password. Other sessions are
  revoked, this one stays. Wrong current password: 403 with one message.
- There is no registration route. Accounts come from the command line.

## User administration

System admins only: 503 when auth is off, 401 without a token, 403 for
others. Responses never include passwords, hashes or sessions.

- `GET /admin/users` (`query` on email or name, `is_active`,
  `is_system_admin`, paged), `POST /admin/users` (409 for a used email),
  `GET /admin/users/{id}`
- `PATCH /admin/users/{id}/status` with `{"is_active": false}` deactivates and
  revokes all sessions; `true` reactivates without restoring old sessions.
  Deactivating the last active system admin: 409.
- `GET /admin/users/{id}/sessions` (with `active`, never tokens),
  `DELETE /admin/users/{id}/sessions/{session_id}` (another user's session:
  404), `POST /admin/users/{id}/revoke-sessions` (returns the count).

## Organizations

Auth only: 503 when auth is off, 401 without a valid token.

- `POST /organizations` (creator becomes owner), `GET /organizations` (mine,
  with my role), `GET /organizations/{id}`
- `GET /organizations/{id}/members`, `POST /organizations/{id}/members`
  (by `user_id`), `PATCH` and `DELETE /organizations/{id}/members/{user_id}`
- Not a member: 404. Member without the right role: 403. Removing or demoting
  the last owner: 409.

- `GET /organizations/{id}/access-summary`: counts of members by role,
  active and inactive members, invitations by status, open and closed
  investigations, and collaborators by role. Owners, admins and system
  admins; other members 403.

## Invitations

Auth only. Owners invite admins, members and viewers; admins invite members
and viewers; system admins may manage any organization's invitations.

- `POST /organizations/{id}/invitations` with `email` and `role`: the only
  answer that holds `invitation_token`, once. A pending invitation for the
  same address or an existing member: 409.
- `GET /organizations/{id}/invitations` (`status`: pending, accepted,
  revoked, expired): never tokens or hashes.
- `DELETE /organizations/{id}/invitations/{invitation_id}`: revoke a pending
  one (again: no change; accepted or expired: 409).
- `POST /organization-invitations/accept` with `token`: the signed in user's
  email must match (else 403). Unknown, expired, revoked and used tokens: the
  same 404. Already a member: 409, and the invitation stays pending.

## Security

- `GET /security/audit`: newest first, filters `organization_id`,
  `actor_user_id`, `action`, `resource_type`, `resource_id`, `created_from`,
  `created_to`, paged. System admins: everything. Organization owners and
  admins: must name an organization they manage (422 without, 404 for other
  organizations). Members, viewers and others: 403.

## Retention

Auth only. Organization owners, admins and system admins read; only system
admins change or delete.

- `GET /organizations/{id}/retention`: `security_audit_days` (null means
  indefinitely) and `updated_at` (null when never set).
- `PUT /organizations/{id}/retention` with `{"security_audit_days": 30..3650
  or null}`: system admins; recorded as `security.audit_retention_changed`.
- `GET /organizations/{id}/retention/audit-preview`: retention days, cutoff
  and how many of the organization's events are older.
- `POST /organizations/{id}/retention/audit-cleanup` with `limit` and
  `"confirm": true` (else 422): system admins; deletes the oldest eligible
  events first and records `security.audit_retention_cleanup` with the
  count. Without a policy: 409. Events without an organization are never
  touched.

## Admin web app

`web/` uses the routes above under `/auth`, `/admin/users`,
`/organizations`, `/organization-invitations` and `/security`, and the
content routes below with the active organization's `organization_id`.

## Health

- `GET /health`

## Sources and ingestion

- `POST /sources`, `GET /sources`, `GET /sources/{id}`, `DELETE /sources/{id}`.
  The list is paged and accepts `query` over names and URLs.
- `PUT /sources/{id}/schedule`, `DELETE /sources/{id}/schedule`
- `GET /sources/{id}/provenance`: observed counts and dates, no score
- `POST /sources/compare`: 2 to 10 sources side by side, with shared clusters,
  entities and claims; no score or ranking
- `POST /ingestion-runs` queues a run and its job for a worker (web and RSS
  sources; other types 409), `GET /ingestion-runs` (oldest first),
  `GET /ingestion-runs/{id}`
- Scoped with auth on: lists need `organization_id` (system admins without it
  see legacy sources); creating a source needs `organization_id` and the
  owner or admin role; schedules, deletes and ingestion runs need owner or
  admin; reading needs any role. Another organization's source: 404.

## Documents

- `POST /documents`, `GET /documents`, `GET /documents/{id}`,
  `DELETE /documents/{id}`
- `GET /documents/{id}/revisions`, `GET /documents/{id}/revisions/{version}`
- `GET /documents/{id}/chunks`: the document's chunks in position order,
  paged, each with its chunk ID, position, text and metadata. Scoped through
  the document's source.
- `GET /documents/{id}/chunks/{chunk_id}`: one chunk, looked up directly; a
  chunk of another document is not found. The web app uses it to focus
  evidence without scanning pages.
- `GET /documents/{id}/chunks/{chunk_id}/context`: that chunk with the one
  before and after it by position, for Previous/Next passage navigation.
- `GET /documents/files/limits`: the content types that have a parser and
  the size limit (50 MB).
- `POST /documents/files?source_id=&filename=`: the raw file is the body and
  `Content-Type` its type. It is stored as a new document of an upload
  source and queued for processing, like `import-file`. Unsupported types,
  empty and too large files: 422; a source that is not an upload source:
  409; no file storage: 503. With `organization_id`, the source must belong
  to it.
- Scoped with auth on through the document's source: reading needs any role,
  adding, uploading and deleting need member or higher. There is no file
  download route.

## Search and embeddings

Scoped with auth on: `organization_id` picks the organization (system admins
without it get legacy content); `source_id` must be a source the caller may
read. The filter is in the SQL, before ranking, fusion, reranking and limits.

- `GET /search` (lexical), `GET /search/semantic`, `GET /search/hybrid`,
  `GET /search/reranked`. Semantic and hybrid name `provider` and `model`;
  the web app sends the local E5 model.
- `GET /embeddings/coverage`

Entity, claim and event evidence rows also carry `document_title`,
`source_id` and `source_name`, joined from the document and its source, so
the web app needs no extra request to label them. These come only from
evidence already in scope.

## Entities, events and claims

Scoped with auth on through `organization_id`. Entities and claims are shared
rows: they are listed only with mentions or evidence in the organization, and
counts and details show only those. Events need evidence in it. Cluster
details show only member events and evidence in it. Link suggestions compare
only events in it. Coverage routes count its chunks, or check the document's
organization when `document_id` is given.

All read only. Coverage routes read the database and never load a model.

- `GET /entities`, `GET /entities/coverage`, `GET /entities/{id}`
- `GET /events`, `GET /events/coverage`, `GET /events/{id}`
- `GET /events/{id}/link-suggestions`: advisory similar events (E5); changes
  nothing; 503 without local embeddings
- `GET /claims`, `GET /claims/coverage`, `GET /claims/{id}`

## Timeline

Scoped with auth on: only clusters with member evidence in the organization,
with counts and sources from that evidence only.

- `GET /timeline`: event clusters in time order, with event, source and
  evidence counts.
- `GET /event-clusters/{id}`: one cluster with its members and their evidence
  (no document text). There is no merge or split route.

## Research

Scoped with auth on. `POST /research/context` and `POST /research/answer`
take `organization_id` in the body (any role); only that organization's
evidence is searched and given to the model. `POST /research/sessions` needs
`organization_id` and member or higher, and a `source_id` of the same
organization; reading a session needs any role there, adding turns member or
higher, and turns only search its organization. Legacy sessions are for
system admins.

- `POST /research/context`: numbered evidence, no answer.
- `POST /research/answer`: answer with checked citations. 503 unless local
  answers are enabled.
- `POST /research/sessions`, `GET /research/sessions` (the
  `organization_id` organization's sessions, newest first, paged; any role),
  `GET /research/sessions/{id}`
- `POST /research/sessions/start`: create a session and its first turn in one
  workflow, with one retrieval and at most one answer generation.
- `GET /research/sessions/{id}/turns`, `POST /research/sessions/{id}/turns`:
  each turn has its question, answer (or null without a model), citations and
  evidence summaries. Prompts and chunk text are not returned.
- `GET /research/sessions/{id}/export?format=json|markdown`: every turn with
  its saved evidence; never searches again.

## Investigations

With auth off, global: everyone who can reach the API sees all of them. With
auth on, every route needs a token; create needs an `organization_id` the user
belongs to; lists show only what the user may view; no view access gives 404,
view without the needed role gives 403. See [[07 Decisions]] for the roles.

- `POST /investigations`, `GET /investigations` (`status` and
  `organization_id` filters, paged; the organization filter never widens
  what the user may see),
  `GET /investigations/{id}`, `PATCH /investigations/{id}`,
  `DELETE /investigations/{id}`
- `POST /investigations/{id}/items`, `GET /investigations/{id}/items`,
  `DELETE /investigations/{id}/items/{item_id}`
- `POST /investigations/{id}/research-sessions/{session_id}`: save a session
  once (201 new, 200 already saved)
- `GET /investigations/{id}/export?format=json|markdown`: saved snapshots
  grouped by type, with whether each record still exists.
- A closed investigation answers 409 to changes until it is reopened.
- `GET /investigations/{id}/members`, `POST /investigations/{id}/members`
  (by `user_id`, role defaults to viewer), `PATCH` and
  `DELETE /investigations/{id}/members/{user_id}`. Auth only. The last owner
  stays; closed investigations can still be shared.

## Operations

Auth only (503 when auth is off, 401 without a token). `organization_id` is
required, also for system admins; owners and admins of that organization and
system admins may look, members and viewers get 403, others 404. Queues:
`ingestion`, `processing`, `embedding`, `entity_extraction`,
`event_extraction`, `claim_extraction`.

- `GET /operations/overview`: per queue, pending, running and failed counts,
  the oldest pending `available_at` and the oldest failed `finished_at`.
  States as stored: a running job with an expired lease counts as running.
- `GET /operations/jobs?queue=&status=failed`: failed jobs, newest failure
  first, paged. Each has the record it works on (source, document or chunk),
  provider and model for chunk jobs, attempts, times and the short stored
  error. Unknown queues: 422.
- `GET /operations/history`: durable worker attempts, newest first and paged.
  Filters: queue, outcome, resource type and ID, and created-from/to. It
  returns only safe identifiers, times, outcomes and sanitized errors.
- `POST /operations/jobs/{queue}/{job_id}/retry` with `{"organization_id"}`:
  puts one failed job back in its queue, available now, and returns its new
  state. Chunk jobs go through the queue's own requeue (409 when results are
  already current), processing jobs become pending, and a failed ingestion
  gets a new run (409 while the source has a queued or running one). The
  attempt count is kept. Not failed: 409; another organization's or unknown
  job: 404. Recorded as `operations.job_retried` with the queue name.

## Dashboard

Scoped with auth on through `organization_id`: every count, queue count and
daily series covers one organization. System admins without it get legacy
content, never all organizations together.

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
Portable tenant archives are administered with `POST` and `GET`
`/organizations/{organization_id}/exports`, inspected at
`/organizations/{organization_id}/exports/{export_id}`, and downloaded from
the nested `/download` route or verified with the nested `POST /verify` route
after authorization. Owners, admins and system
admins may use them. `signalscope export-organization ORGANIZATION_ID
--output FILE.zip` builds the same versioned archive locally.
`signalscope verify-organization-export FILE.zip` verifies a local archive,
and `signalscope cleanup-organization-exports` previews retention cleanup;
`--apply` expires the selected artifacts.
There is no relation route, because no relations are stored.

See [[06 Search and AI]] for the models behind these routes.
