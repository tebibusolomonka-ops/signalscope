# Current State

Batch 314 to 333 (organization content tenancy) needed six corrective
commits and ended at repository commit 339 (`5b1fcaa`). Current batch: 340
to 359, the tenant research workspace in the web app. Alembic head:
`a809b1740bcd` (Add event cluster organization).

## Done

- Authentication foundation (commits 273 to 277): users, Argon2id password
  credentials, opaque server-side sessions, and `POST /auth/login`,
  `POST /auth/logout`, `GET /auth/me`. Off by default
  (`SIGNALSCOPE_AUTH_ENABLED=false`); then every existing API works as before.
- `signalscope create-user` makes accounts (the first system admin too); the
  password is asked for or read from standard input, never an option.
- Organizations with owner, admin, member and viewer roles, and
  `/organizations` routes. Auth only.
- Investigation ownership: an organization, a creator and collaborators with
  owner, editor or viewer roles, checked by `InvestigationAccess`. With auth
  on, the investigation API needs a token and filters by access, and
  `/investigations/{id}/members` manages collaborators. With auth off it works
  as before.
- Session management (`GET /auth/sessions`, `DELETE /auth/sessions/{id}`,
  `POST /auth/logout-all`) and `signalscope cleanup-auth-sessions`, which
  deletes sessions that ended more than the retention period ago.
- Security audit events for account creation, logins, logouts and changes to
  organizations, members and collaborators, written in the same transaction
  as the change. No read API yet.
- An end to end test covers bootstrap, login, organizations, sharing,
  logout-all and the audit log, plus the auth-off behavior.
- User administration for system admins (`UserAdministrationService`,
  `/admin/users`): list with search and filters, detail, create, and
  deactivate or reactivate. Deactivating revokes every session; the last
  active system admin cannot be deactivated.
- Self-service password change (`POST /auth/change-password`), which revokes
  the user's other sessions.
- Organization invitations: create, list with a computed status, revoke,
  and accept (`OrganizationInvitationService`). The raw token is returned
  only when an invitation is made; delivery is manual.
- Security audit reading (`SecurityAuditQueryService`, `GET /security/audit`).
- `signalscope cleanup-organization-invitations` removes old used, revoked
  and expired invitations.
- Admin session controls under `/admin/users/{id}/sessions`.
- Organization access summary (`GET /organizations/{id}/access-summary`).
- An administration end to end test covers the whole backend flow.
- The admin web app in `web/` (React, JavaScript, Vite): sign in, dashboard,
  organizations with members, invitations and access summary, users, and
  security (audit log and sessions). CI lints, tests and builds it.
- Content tenancy, in progress: sources have an organization (NULL for
  legacy sources), `ContentAccessPolicy` decides access, and these routes
  are scoped: sources, ingestion runs, documents and revisions, all four
  search modes, entities, claims, events, event cluster detail, link
  suggestions, the four coverage routes, the timeline, provenance,
  comparison, the three dashboard routes, research context and answers, and
  research sessions (which now have their own organization). Investigation
  items must belong to the investigation's organization, and
  `import-file --organization-id` checks the upload source. Event clusters
  have an organization and the linker never mixes organizations.
  `signalscope assign-source-organization` moves a legacy source in, once.
  A route audit test checks every content route for leaks between
  organizations. The web app has an active organization picker and a
  dashboard scoped to it.

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
  research sessions, each with a snapshot. Global when auth is off; owned
  by an organization and shared with collaborators when it is on.
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
