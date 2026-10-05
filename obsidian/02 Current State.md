# Current State

Batch 420 to 459 is complete, pushed and green. Batch 460 to 479 is implemented:
disaster-recovery drills, operational observability, session hardening, and
input and abuse protection. The remaining 480 to 489 deployment evidence,
acceptance and release-readiness work is in progress. Alembic head is
`d8e2f4a6b1c3` (Add active operation guards).
Durable operation history and portable organization
exports, model evaluation evidence tooling and authentication hardening were
complete through commit 414, and exact evidence navigation through commit
419. Measured evaluation reports can now be imported, listed, compared and
reviewed by system admins (`evaluation_report_records`, the `/admin/evaluations`
API and a web workspace); importing stores a report and never runs a model.
Evidence navigation is complete through planned commit 419: a paged document
chunk API, a focused chunk on the document page, and search results and
research citations that link to the exact passage.

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
- Organization operations, in progress: `GET /operations/overview` (job
  counts per queue), `GET /operations/jobs` (failed jobs) and
  `POST /operations/jobs/{queue}/{job_id}/retry` (audited) for owners,
  admins and system admins of one organization. Worker claims and outcomes
  for all six queues are durable tenant history, exposed by the filtered,
  paged `GET /operations/history` route and the operations workspace.
- Portable organization exports: durable export records, a deterministic
  versioned ZIP with tenant-scoped JSON and JSONL files, per-member checksums,
  in-memory verification, bounded retention cleanup, safe global Entity
  and Claim scoping through tenant evidence, BlobStore artifacts, owner/admin
  API administration and downloads, `signalscope export-organization`, and
  the `/organizations/:organizationId/exports` workspace with factual
  verification results. Raw document assets are included at deterministic ZIP
  paths and checked against both their database records and manifest entries.
  Configurable asset count and byte limits are shown in the workspace and
  enforced before asset reads. Passwords, session hashes, invitation hashes
  and model caches are not exported. System admins can upload an archive to a
  read-only restore planning workspace.
- Organization restore writes an archive into an empty target organization
  (one with no sources, investigations, research sessions or event clusters);
  it never overwrites populated tenants. Before any change it re-verifies the
  archive, builds the inventory, checks conflicts and validates user mappings.
  Every archived user must map to an existing active user; users are never
  created. Canonical entities and claims are reused, only the target's evidence
  is restored, ids that cannot be reused are remapped, and binary assets are
  staged then stored with checksum checks. Passwords, hashes, sessions, bearer
  tokens, raw invitation tokens and login throttle state are never restored.
  Restores have durable lifecycle records and audit events, a system-admin
  apply API (`POST /organizations/:id/restore`) and a `signalscope
  restore-organization` command that is a dry run unless `--apply` is given.
- Sessions have absolute and idle lifetimes
  (`SIGNALSCOPE_AUTH_SESSION_MAX_AGE_SECONDS`, 7 days;
  `SIGNALSCOPE_AUTH_SESSION_IDLE_SECONDS`, 1 day). Session validation revokes a
  session past either limit; activity refreshes the idle clock but never the
  absolute one. The session inventory (self and admin) reports the effective
  expiry, users can sign out other sessions while keeping the current one
  (`POST /auth/sessions/revoke-others`), and revocations are audited. No token,
  token hash or password is ever returned or logged.
- Operational observability builds on operation attempt history. An operation
  trend service gives factual time-bucket (hour/day) counts of attempts,
  successes, failures, recovered and retried attempts, and a latency service
  gives per-queue completed-count, min/max/average and p50/p95 durations
  (percentile_disc, deterministic). Both are organization-scoped. A
  `GET /operations/trends` API (owner/admin/system admin) and an Operations
  workspace section present them as plain tables, with no subjective health score
  or organization ranking.
- Disaster recovery drills exercise backup and restore readiness and record the
  factual result (`organization_disaster_recovery_drills`). A verification-only
  drill backs up, verifies and plans a restore without changing data; a
  restore-test drill also restores into a separate empty target using the
  constrained restore service. Owners/admins/system admins run verification
  drills; restore-test needs a system admin. There is an admin API
  (`/organizations/:id/drills`), a `signalscope run-disaster-recovery-drill`
  command and a Disaster recovery web workspace. Drills never create, delete or
  overwrite organizations and never restore credentials, sessions or throttles.
- Production readiness and deployment diagnostics are factual and read-only. A
  dependency readiness service checks the database, file storage, scheduler and
  job queues and reports configured local models without loading or downloading
  them. `GET /health/live` answers even when the database is down; `GET
  /health/ready` answers 503 when a required dependency is unavailable. A queue
  readiness service reports waiting, running, oldest waiting age and expired
  lease counts per queue without reading tenant payloads. A production
  configuration validator (`signalscope validate-production-config`) and
  deployment diagnostics (`signalscope deployment-diagnostics`) combine the
  environment summary, configuration result, readiness, migration head and
  current revision and queue counts. None of them run migrations, change queues,
  load a model or print a secret.
- HTTP responses carry security headers (nosniff, Referrer-Policy, X-Frame-Options,
  Permissions-Policy) and a content security policy that is restrictive in
  production and development-compatible otherwise. A support bundle
  (`signalscope create-support-bundle`) writes a safe ZIP of configuration,
  migration state, readiness, queue counts and recent short worker errors with
  checksums, and never secrets or tenant content. A pilot readiness evaluator
  (`signalscope pilot-readiness`) produces a factual checklist of passed, failed,
  warning and manual checks, with local model evidence reported separately; a
  missing model never fails the pilot on its own. End-to-end coverage ties auth,
  organization content, backup, export verification, restore planning, readiness,
  headers, CSP, the support bundle and pilot readiness together and checks tenant
  isolation and that no secret or tenant content leaks.
- Organization backups reuse the versioned export archive. One policy per
  organization controls daily or weekly scheduling, retained backup count and
  binary asset inclusion. A backup is completed only after archive verification;
  owners, admins and system admins can manage policy, run one immediately and
  inspect recent verified or failed runs in the web workspace. Backup retention
  never expires manually created exports.
- Request and operation abuse protections are in place. JSON and non-JSON
  request bodies have separate configurable limits, including streamed bodies
  without a Content-Length header. User-controlled list queries use bounded
  limits and non-negative offsets. PostgreSQL partial unique indexes prevent
  duplicate running exports or backups for one organization, active restores
  for one target, and concurrent restore-test drills for one target. Terminal
  history and unrelated organizations remain available.
- Explicit developer benchmarks report the local model environment and run
  embedding, reranker, structured extraction and fixed-evidence answer model
  measurements. Normal tests and CI use fakes and never load or download models.
- Versioned dataset manifests and report envelopes support factual comparison,
  user-defined quality gates, and deterministic evidence bundles with checksums.
- Relation benchmark tooling measures exact normalized triples globally and by
  type, analyzes available confidence values, applies user-defined readiness
  gates, and produces a factual summary. Relation persistence is not implemented.
- Failed logins are safely audited and limited with shared PostgreSQL throttle
  state. System admins can inspect and clear that state through an audited API;
  a local recovery command is also available. Emails and secrets are not stored.
- Audit retention: a per-organization policy (indefinite by default), a
  preview for owners and admins, cleanup for system admins through the API
  or `signalscope cleanup-security-audit --apply`.
- Web pages for operations (queue counts, failed-job retry, attempt history) and audit
  retention, an event detail page, and entity, claim and event evidence that
  now carries the document title and source name.
- Tenant resource selectors page through Sources and open Investigations;
  Source selectors search on the server and do not stop at the first 100.
- Source ingestion runs poll every five seconds while a recent run is active,
  and stop when all visible runs are terminal.
- `POST /research/sessions/start` creates a session and its first turn without
  repeating retrieval or answer generation. `/research/new` uses it directly.
- Tenant research workspace in the web app, done: content navigation that
  needs an active organization, sources (list, create,
  detail, provenance, ingest now, schedule, run history, delete), documents
  (list, detail, revisions, delete), file import, search in all four modes,
  entities, claims, the event timeline, event clusters, source comparison,
  investigations with saved items and collaborators, research sessions with
  multi-turn questions, one-shot research, and JSON and Markdown exports of
  sessions and investigations. `POST /ingestion-runs` now also queues the ingestion
  job, for web and RSS sources only. `POST /documents/files` stores an
  uploaded file like `import-file`. `GET /investigations` takes an optional
  `organization_id`. `GET /research/sessions` lists an organization's
  sessions.

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
