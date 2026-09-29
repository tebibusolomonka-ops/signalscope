# API Map

All routes are JSON over HTTP. Only the auth, admin, organization and (with
auth on) investigation routes check a bearer token; the rest stay open. Routes that need the
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

## Organizations

Auth only: 503 when auth is off, 401 without a valid token.

- `POST /organizations` (creator becomes owner), `GET /organizations` (mine,
  with my role), `GET /organizations/{id}`
- `GET /organizations/{id}/members`, `POST /organizations/{id}/members`
  (by `user_id`), `PATCH` and `DELETE /organizations/{id}/members/{user_id}`
- Not a member: 404. Member without the right role: 403. Removing or demoting
  the last owner: 409.

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

With auth off, global: everyone who can reach the API sees all of them. With
auth on, every route needs a token; create needs an `organization_id` the user
belongs to; lists show only what the user may view; no view access gives 404,
view without the needed role gives 403. See [[07 Decisions]] for the roles.

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
- `GET /investigations/{id}/members`, `POST /investigations/{id}/members`
  (by `user_id`, role defaults to viewer), `PATCH` and
  `DELETE /investigations/{id}/members/{user_id}`. Auth only. The last owner
  stays; closed investigations can still be shared.

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
