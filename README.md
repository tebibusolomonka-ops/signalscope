# SignalScope

## Model evaluation workflow

Evaluation is explicit and evidence-based:

1. Run `signalscope model-environment` to inspect the local runtime without loading models.
2. Run only the selected benchmark commands for the models and tasks being assessed.
3. Use `signalscope compare-evaluation-reports` when factual report differences are useful.
4. Use `signalscope check-evaluation-report` with a user-defined quality profile.
5. Use `signalscope bundle-evaluation-reports` to package completed reports and supporting evidence.

Bundling does not run or download models.

### Relation evaluation

Prepare a versioned relation benchmark dataset, run the relation benchmark,
inspect exact-match type metrics and confidence observations when available,
apply project-defined readiness gates, and review the factual relation summary.
Humans decide whether later persistence work is justified. Relation persistence
remains deferred and is not implemented.

SignalScope is a media intelligence and research platform. The plan is to collect
content from sources such as articles, websites, RSS feeds, documents, audio and
video, and turn it into structured information that can be searched and analyzed.

## Status

Early development. SignalScope can collect RSS feeds and web pages, import
plain text, JSON, HTML, PDF and DOCX files, and search the collected text
through an HTTP API, by words or, with local embeddings, by meaning. There is
no user interface and no authentication yet.

## Development

SignalScope needs Python 3.12 or newer.

Set up a virtual environment and install the package with the dev tools:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

The `obsidian/` folder is project knowledge for maintainers and coding agents:
Markdown notes on the architecture, current state, decisions and known issues.
The code and migrations stay the source of truth.

Settings come from `SIGNALSCOPE_*` environment variables. See
[docs/configuration.md](docs/configuration.md).

Run the API locally. SignalScope logs each request itself, so the Uvicorn
access log is turned off:

```bash
uvicorn signalscope.api.app:create_app --factory --reload --no-access-log
```

## Request and operation safeguards

The API rejects JSON bodies larger than 1 MB by default and non-JSON uploads,
including organization archives, larger than 512 MB. Configure the limits with
`SIGNALSCOPE_MAX_JSON_REQUEST_BYTES` and
`SIGNALSCOPE_MAX_UPLOAD_REQUEST_BYTES`. Declared and streamed body sizes are
checked before a route can process an oversized payload. Document files and
the contents of organization archives keep their own tighter validation.

User-controlled list queries use bounded `limit` and non-negative `offset`
parameters. The shared maximum page size is 100; organization exports,
backups and disaster-recovery drill history use the same bounds without
changing their existing response shapes.

Organization exports and manual backups share a PostgreSQL guard that permits
only one running archive operation per organization. Restores permit one
planned or running operation per target, and restore-test drills permit one
running drill per target. Unrelated organizations and completed or failed
history are not blocked. Conflicting requests return HTTP 409.

Start the local PostgreSQL database and point SignalScope at it. The user,
password and database name in `compose.yaml` are all `signalscope`. They are
for local development only, so do not use them anywhere else.

```bash
docker compose up -d postgres
export SIGNALSCOPE_DATABASE_URL=postgresql+asyncpg://signalscope:signalscope@localhost:5432/signalscope
```

Stop it with `docker compose down`. Add `-v` to delete the data as well.

Apply database migrations. This needs `SIGNALSCOPE_DATABASE_URL`:

```bash
alembic upgrade head
```

Create a new migration:

```bash
alembic revision -m "Describe the change"
```

Run the checks. This runs pytest, Ruff, the format check and mypy in order,
stops at the first failure and checks that there is one Alembic head:

```bash
python scripts/check.py
```

Database tests run only when `SIGNALSCOPE_TEST_DATABASE_URL` is set. Otherwise
they are skipped. The tests delete data, so the database name must end with
`_test`. With the local Compose database:

```bash
docker compose exec postgres createdb -U signalscope signalscope_test
export SIGNALSCOPE_TEST_DATABASE_URL=postgresql+asyncpg://signalscope:signalscope@localhost:5432/signalscope_test
pytest
```

## Accounts and sign in

Authentication is off by default, and then every API works without a login.
To turn it on, create the first account from the command line, then enable it:

```bash
signalscope create-user admin@example.org --display-name "Admin" --system-admin
export SIGNALSCOPE_AUTH_ENABLED=true
```

`create-user` asks for the password twice without showing it. For automation,
`--password-stdin` reads it from the first line of standard input instead.
There is no option that takes the password itself, so it never lands in shell
history. Passwords must be 12 to 1024 characters. There is no self
registration: more accounts are made the same way, without `--system-admin`.

Sign in with the email and password to get a bearer token. The token is shown
only in this answer; keep it secret.

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.org", "password": "<your password>"}'
```

Send it with every protected request, and end the session with
`POST /auth/logout`:

```bash
curl http://localhost:8000/auth/me -H "Authorization: Bearer <token>"
```

Sessions are opaque, server-side and revocable; only a hash of the token is
stored, and no JWT is used. A failed login always gives the same answer,
including for unknown and inactive accounts and temporarily blocked logins.
Failed attempts are counted in PostgreSQL by a one-way email identifier. By
default, 10 failures within 15 minutes block further attempts for 15 minutes.
Set `SIGNALSCOPE_AUTH_LOGIN_WINDOW_SECONDS`,
`SIGNALSCOPE_AUTH_LOGIN_MAX_FAILURES` and
`SIGNALSCOPE_AUTH_LOGIN_BLOCK_SECONDS` to change those limits.

With authentication on, every content route needs a token too, and content
belongs to organizations through its source. Lists, searches, the timeline,
dashboards and research take `organization_id` and only show that
organization's content; a single source, document or session is checked
against its own organization. With authentication off, everything stays open
as before.

### Administration

After the first system admin exists (from `create-user`), the usual backend
workflow is:

1. The system admin creates accounts with `POST /admin/users`, lists and
   searches them with `GET /admin/users?query=...&is_active=true`, and turns
   them off or on with `PATCH /admin/users/{id}/status` and
   `{"is_active": false}`. Turning an account off ends all its sessions. The
   last active system admin cannot be turned off.
2. A signed in user creates an organization, adds members or invites people
   (see below), and starts investigations in it.
3. System admins can see and end another user's sessions:
   `GET /admin/users/{id}/sessions`,
   `DELETE /admin/users/{id}/sessions/{session_id}` and
   `POST /admin/users/{id}/revoke-sessions`.
4. System admins inspect failed-login state with
   `GET /admin/auth/throttles?limit=50&offset=0` and clear one with
   `DELETE /admin/auth/throttles/{identifier}`. A local administrator can use
   `signalscope clear-login-throttle <identifier>`. Neither interface exposes
   the email behind the one-way identifier.
5. Owners and admins read `GET /organizations/{id}/access-summary` for counts
   of members by role, active and inactive members, invitations by status,
   investigations and collaborators, and the audit log (below).

Only system admins can create accounts through the API; there is no public
registration.

### Organizations

`POST /organizations` makes an organization and you become its owner. Members
are added by user ID with `POST /organizations/{id}/members`. Roles:

- `owner`: manages everyone and has full access to the organization's
  investigations. An organization always keeps at least one owner.
- `admin`: manages members and viewers, with full access to investigations.
- `member` and `viewer`: see only the investigations they collaborate on.

Users who are not members get 404. System admins can manage any organization.

### Invitations

There is no email sending yet, so invitations are shared by hand:

1. An owner or admin invites an address with
   `POST /organizations/{id}/invitations` and
   `{"email": "person@example.org", "role": "member"}`. Owners may invite
   admins, members and viewers; admins may invite members and viewers. Nobody
   is invited as owner.
2. The answer holds `invitation_token`. It is shown only once and only its
   hash is stored. Send it to the person over a secure channel, never in a
   public place.
3. `GET /organizations/{id}/invitations` lists invitations with a computed
   `status` (`pending`, `accepted`, `revoked` or `expired`), never the token.
   `DELETE /organizations/{id}/invitations/{invitation_id}` revokes one.
4. The person signs in with the account for the invited address and sends
   the token to `POST /organization-invitations/accept` as `{"token": "..."}`.
   They join with the invited role. A token works once; unknown, expired,
   revoked and used tokens all answer 404. Someone who is already a member
   gets 409 and the invitation stays pending.

Invitations expire after `SIGNALSCOPE_ORGANIZATION_INVITATION_DAYS` days (7 by
default).
Accepted, revoked and expired invitations are kept for
`SIGNALSCOPE_ORGANIZATION_INVITATION_RETENTION_DAYS` days (30 by default).
Delete older ones from a scheduled job:

```bash
signalscope cleanup-organization-invitations --limit 1000
```

### Sessions

Signed in users can see their sessions with `GET /auth/sessions` (never the
tokens), revoke one with `DELETE /auth/sessions/{session_id}`, sign out every
other session but keep the current one with `POST /auth/sessions/revoke-others`,
and end every session, the current one included, with `POST /auth/logout-all`.
Each listed session shows its effective expiry, the earliest of its stored
expiry and the absolute and idle limits.

Two limits bound every session. The absolute limit is
`SIGNALSCOPE_AUTH_SESSION_MAX_AGE_SECONDS` (7 days by default), measured from
when the session was created and never extended by activity. The idle limit is
`SIGNALSCOPE_AUTH_SESSION_IDLE_SECONDS` (1 day by default), measured from the
last use. A session past either limit stops working and is revoked; the idle
limit must not exceed the absolute limit.

Change your password with `POST /auth/change-password` and
`{"current_password": "...", "new_password": "..."}`. Your other sessions are
revoked and the current one stays signed in.

Expired and revoked sessions stay in the database for
`SIGNALSCOPE_AUTH_SESSION_RETENTION_DAYS` days (30 by default). Delete older
ones from a daily scheduled job:

```bash
signalscope cleanup-auth-sessions --limit 1000
```

It prints how many sessions it checked and deleted. Active sessions are never
deleted.

### Legacy content

Sources made before organizations existed have no organization. With
authentication on, only system admins see them and what was made from them.
Move one such source into an organization, once, with:

```bash
signalscope assign-source-organization <source-id> <organization-id>
```

Its documents, extracted data and source-limited research sessions then belong
to that organization. Its events leave their legacy clusters and are linked
again inside the organization. Investigations are not changed. A source that
already has an organization cannot be moved.

### Security audit

Account creation, successful and failed logins, logouts, throttle clearing,
and changes to organizations, members and investigation collaborators are
written to the `security_audit_events` table. Events hold safe IDs, roles and
failure reasons only, never emails, passwords, tokens or hashes.

Read them with `GET /security/audit`, newest first. Filters: `action`,
`resource_type`, `resource_id`, `actor_user_id`, `created_from` (inclusive),
`created_to` (exclusive), plus `limit` and `offset`. System admins see every
event. Organization owners and admins must pass `organization_id` for an
organization they manage and only see its events. Members and viewers get 403.

```bash
curl "http://localhost:8000/security/audit?organization_id=<id>&action=auth.login" \
  -H "Authorization: Bearer <token>"
```

### Audit retention

By default an organization's audit events are kept indefinitely. A system
admin may set how many days they are kept, from 30 to 3650, or set it back to
`null` for indefinitely:

```bash
curl -X PUT "http://localhost:8000/organizations/<id>/retention" \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"security_audit_days": 365}'
```

Setting a policy deletes nothing. Organization owners and admins can read the
policy (`GET /organizations/<id>/retention`) and see how many events it makes
eligible (`GET /organizations/<id>/retention/audit-preview`), but they cannot
change it or delete events. Only a system admin deletes, with
`POST /organizations/<id>/retention/audit-cleanup` and
`{"limit": 1000, "confirm": true}`; the oldest eligible events go first, and
the cleanup is itself recorded as a new audit event. Events without an
organization, such as logins, are never deleted this way. Policy changes are
recorded too.

On the server, the same cleanup runs as a local administrator. It only shows
the numbers unless `--apply` is given:

```bash
signalscope cleanup-security-audit --organization-id <id>
signalscope cleanup-security-audit --organization-id <id> --limit 1000 --apply
```

It prints the organization, the retention days, how many events are eligible
and how many were deleted, never the events themselves.

## Operations and observability

Each worker attempt is recorded as durable operation history. Owners, admins and
system admins can review one organization's operations at `/operations`: queue
counts, failed jobs with retry, the attempt history, and factual trends. The
trends come from `GET /operations/trends?organization_id=<id>` and combine
attempt-outcome counts per time bucket (hour or day) with per-queue latency
summaries (count, min, max, average, p50 and p95 of completed attempt
durations). These are counts, not a health score, and never mix organizations:
every query is filtered to the one organization, and a caller who is not an
owner, admin or system admin there is refused.

## Organization backup and restore

A system admin can export one organization to a portable ZIP archive. The
archive holds the organization's own tenant content as JSON, with its binary
document assets and a manifest of checksums. It never holds passwords, password
hashes, sessions, bearer tokens, raw invitation tokens or login throttle state.

```bash
signalscope export-organization <id> --output tenant.zip
signalscope verify-organization-export tenant.zip
```

Scheduled backups reuse the same archive. Each organization has a backup policy
(`GET`/`PUT /organizations/<id>/backup-policy`), and a system admin can run one
now with `POST /organizations/<id>/backups/run` or
`signalscope run-organization-backup <id>`.

Restore is deliberately constrained. It only writes into an empty target
organization: one with no sources, investigations, research sessions or event
clusters. It never overwrites a populated organization.

Before any data changes, the server re-verifies the archive, reads its
inventory, checks for conflicts, and validates how archived users map to
existing users. Every archived user must map to an existing active user; users
are never created by a restore. A default suggestion maps each archived user to
the existing user with the same id and shows that user's email to confirm. A
blocking conflict or an unresolved user mapping refuses the restore.

Canonical entities and claims are shared, so the restore reuses the matching
global records and only restores the target organization's own evidence. It
never copies another tenant's evidence. Archive ids that cannot be reused are
remapped, and relationships point at the restored records.

Plan a restore first, which changes nothing:

```bash
signalscope restore-organization tenant.zip <target-organization-id>
```

Apply it only when the plan looks right. `--map` maps an archived user to an
existing user, and may be given more than once:

```bash
signalscope restore-organization tenant.zip <target-organization-id> --apply \
  --map <archived-user-id>:<existing-user-id>
```

Over the API a system admin plans with
`POST /organizations/<id>/restore-plan` and applies with
`POST /organizations/<id>/restore?confirm=true`, sending the archive as the
request body and each mapping as a `user_mapping=<archived>:<existing>` query
value. The server re-verifies the archive every time; it never trusts a caller
that says the archive was already checked. Restores are recorded with their
lifecycle (running, completed or failed) and as audit events.

### Disaster recovery drills

A disaster recovery drill exercises the backup and restore path on purpose and
records the factual result. A verification-only drill backs up an organization,
verifies the archive and plans a restore without changing data. A restore-test
drill also restores into a separate, explicitly chosen empty target
organization using the same constrained restore service; it never creates,
deletes or overwrites an organization and never restores credentials.

Owners, admins and system admins can run verification-only drills; restore-test
drills require a system admin. Over the API:
`POST /organizations/<id>/drills` with `{"mode": "verification_only"}` or
`{"mode": "restore_test", "target_organization_id": "<empty-org>"}`, listed at
`GET /organizations/<id>/drills`. On the server:

```bash
signalscope run-disaster-recovery-drill <id>
signalscope run-disaster-recovery-drill <id> --mode restore-test \
  --target-organization <empty-org-id>
```

The organization administration area has a Disaster recovery workspace that
shows recent drills and runs a verification drill, with restore tests limited to
system admins and an empty target.

## Production readiness and diagnostics

The API has two operational endpoints next to `/health`. `GET /health/live`
reports process liveness and answers even when the database is down. `GET
/health/ready` checks the database, file storage, scheduler and job queues and
answers 503 when a required dependency is unavailable, 200 when ready. Neither
exposes the database URL, credentials or storage secrets. Configured local
models are reported as ready or degraded, but a missing model dependency never
blocks readiness.

Before a deployment, check the configuration for production. It reads flags
only and never prints the database URL or any secret, and it exits nonzero when
there are errors:

```bash
signalscope validate-production-config
```

For a fuller picture, deployment diagnostics combine the model environment, the
production configuration result, dependency readiness, the migration head and
current revision, and factual queue counts. It changes nothing: it never runs
migrations, touches queues, loads a model or prints a secret.

```bash
signalscope deployment-diagnostics
signalscope deployment-diagnostics --json
```

It exits nonzero when the configuration has errors, a required dependency is
unavailable, or the database is not at the current migration head.

For deployment automation, `startup-preflight` reports configuration,
database, storage, migration, queue and build facts without changing them.
Migration compatibility can also be checked separately. Both support JSON and
exit nonzero on a blocking result.

```bash
signalscope startup-preflight --json
signalscope check-migration-compatibility --json
```

`validate-deployment` reads a version 1 JSON profile of explicit requirements,
such as authentication, storage, a current migration, security headers, CSP and
a recent verified backup. It reports requirements met, missed and warnings; it
does not produce a score. Once validation passes, create a deterministic release
candidate manifest. Selected imported evaluation reports are references only.

```bash
signalscope validate-deployment deployment-profile.json --json
signalscope create-release-candidate --profile deployment-profile.json \
  --output release-candidate.json --evaluation-report <report-id>
```

The manifest contains build metadata, the application migration head,
validation results, the latest verified backup reference, selected evaluation
report IDs and fingerprints, a security configuration summary and its creation
time. It contains no database URL, password, token, tenant content or model
prompt, and it does not deploy or migrate anything.

When something goes wrong in a pilot, create a support bundle to share. It is a
ZIP of the configuration summary, migration state, readiness, queue counts and
the recent short worker error messages, each with a checksum. It never contains
passwords, tokens, the database URL, raw document or chunk text, research
answers or private assets.

```bash
signalscope create-support-bundle --output support.zip
```

### Pilot preparation workflow

Before a pilot, work through this list:

1. `signalscope validate-production-config` and fix every error.
2. Apply migrations and confirm `signalscope deployment-diagnostics` reports the
   database at the current head and all dependencies ready.
3. Confirm a manual backup completes and its archive verifies
   (`signalscope run-organization-backup <id>` and
   `signalscope verify-organization-export`), and that a restore plan into an
   empty organization is clean.
4. `signalscope pilot-readiness` for the full checklist. It groups passed,
   failed and warning checks, lists the manual steps a person must confirm (such
   as TLS in front of the API), and reports local model evidence in its own
   section. Missing model evidence does not fail the pilot on its own.

The pilot readiness output is a factual checklist, not a score. Fix the failed
checks, record the manual ones, and keep a support bundle for reference.

## Admin web app

`web/` holds a small React admin app, written in JavaScript and built with
Vite. It needs Node.js 24 or newer. Start the API on port 8000 with
authentication on, then:

```bash
cd web
npm ci
npm run dev
```

The development server proxies `/api` to `http://localhost:8000` (change it
with `SIGNALSCOPE_API_TARGET`). `VITE_SIGNALSCOPE_API_URL` sets the API base
URL the browser uses; it defaults to `/api`. The API sends no CORS headers,
so serve the built app and the API from one origin, for example behind one
reverse proxy. Checks: `npm run lint`, `npm test -- --run` and
`npm run build`.

Content pages, for the active organization:

| Route | What it does |
| --- | --- |
| `/dashboard` | Counts and daily activity |
| `/sources`, `/sources/<id>` | Sources: add (owners and admins), configuration, provenance, ingest now, schedule, recent runs, delete |
| `/sources/compare` | 2 to 10 sources side by side, observed counts only |
| `/documents`, `/documents/<id>` | Filtered document list; text, revisions and delete |
| `/documents/<id>?chunk=<chunk-id>` | The document with that chunk focused and highlighted |
| `/documents/import` | Upload a file into an upload source (members and up) |
| `/search` | Lexical, semantic, hybrid or reranked search, in the API's order |
| `/entities`, `/entities/<id>` | Entities with this organization's mentions |
| `/claims`, `/claims/<id>` | Claims with their evidence; no truth labels |
| `/events`, `/event-clusters/<id>` | Timeline, clusters and advisory similar events |
| `/investigations`, `/investigations/<id>` | Investigations, saved items, collaborators, exports |
| `/research`, `/research/<id>` | Research sessions: questions, answers, citations, evidence, exports |
| `/research/new` | One question without a session: evidence, or evidence and an answer |

Records can be saved to an open investigation from their pages. Exports are
the API's JSON and Markdown, downloaded in the browser with names made from
the record ID; nothing is searched or answered again.

Evidence links lead to the exact passage. A search result, and a research
citation's evidence card, link to `/documents/<id>?chunk=<chunk-id>`, which
opens the document with that chunk highlighted and focused. The chunk ID is
not secret, so it may be in the URL; chunk text, excerpts and the bearer
token never are. Research citations still focus the evidence card in place as
well; opening it in the document is a separate action. Entity, claim and
event evidence rows link to their exact chunk too. The focused passage has
Previous and Next buttons that step through the document and update the
`?chunk=` value. `GET /documents/<id>/chunks/<chunk-id>` looks a chunk up
directly and `GET /documents/<id>/chunks/<chunk-id>/context` returns the
passage before and after it; `GET /documents/<id>/chunks` (paged) lists them.

Administration pages: organizations (members, invitations and the access
summary), users (system admins: search, create, deactivate and see another
user's sessions), security (the audit log for system admins and organization
owners and admins, and your own sessions) and accept invitation, where you
paste a token you were sent.

The shell has an **Active organization** picker with the organizations you
belong to. Content pages need one and show only that organization's data;
switching clears them before the new organization loads, so no page shows
the old organization's data. There is no combined view of several
organizations, also not for system admins. The choice is remembered
for the browser tab in sessionStorage; it is not a secret, because the API
checks every request. Sign in, users, organization management and security
pages keep their own organization rules.

The app keeps your session token in the browser's sessionStorage, never
localStorage, so it is gone when the browser session ends. A new invitation
token is only shown on screen once and is never stored. The app hides actions
you cannot use, but the API makes every permission decision.

## Command line

Fetch new content for one RSS or web source. This needs
`SIGNALSCOPE_DATABASE_URL` and makes real network requests:

```bash
signalscope ingest-source <source-id>
```

It prints the run ID, the status and how many items were seen, created and
skipped as duplicates. The exit code is 0 only when the run completed. Upload
and API sources cannot be ingested from the command line.

Timeouts, connection errors and HTTP 429, 502, 503 and 504 responses are tried
again. A run makes at most 3 attempts and waits 5, then 10 seconds in between.
Documents saved by an earlier attempt are kept and skipped as duplicates.

### Scheduled ingestion

Turn on scheduled ingestion for a web or RSS source through the API, for
example every 60 minutes starting now:

```bash
curl -X PUT http://localhost:8000/sources/<source-id>/schedule \
  -H "Content-Type: application/json" -d '{"interval_minutes": 60}'
```

`DELETE /sources/<source-id>/schedule` turns it off again. Jobs are queued in
PostgreSQL. Queue a job for every source that is due:

```bash
signalscope schedule-ingestion --limit 100
```

It prints how many sources were due and how many jobs it created, for example
`Jobs created: 4`. Then run one queued job:

```bash
signalscope run-worker --once
```

It prints `No ingestion job available.` when there is nothing to do, or the job
ID and its status. The exit code is 0 when the job completed or there was no
job, and 1 when the job failed. `schedule-ingestion` does one pass and exits,
so run it from cron or a systemd timer.

Without `--once`, the worker keeps running and takes jobs as they arrive. It
waits `--poll-seconds` (5 by default) when the queue is empty, and
`--max-jobs` makes it exit after that many jobs. A failed job does not stop
it. Press Ctrl+C, or send SIGTERM, to stop it. The worker then finishes the
job it is working on, takes no new one and exits:

```bash
signalscope run-worker --poll-seconds 10
```

Several workers can run at the same time without taking the same job. A
claimed job has a five minute lease. When a worker crashes, the next worker
puts its job back in the queue once the lease has run out.

### Importing files

Plain text, JSON, HTML, PDF and DOCX files can be imported into an upload
source. This needs `SIGNALSCOPE_DATABASE_URL` and `SIGNALSCOPE_BLOB_DIR`:

```bash
signalscope import-file <source-id> ./report.pdf
```

The content type is guessed from the file name. Pass `--content-type` when the
name does not tell. The command stores the file and queues it for processing,
then prints the document, asset and processing job IDs. It does not parse the
file itself.

The API does the same with `POST /documents/files?source_id=<id>&filename=<name>`:
the request body is the raw file and `Content-Type` its type (at most 50 MB,
only types with a parser; `GET /documents/files/limits` lists them). The web
app's import page uses it.

Parse one queued file:

```bash
signalscope run-processing-worker --once
```

It saves the text on the document and prints the job ID, its status and the
document ID, or `No document processing job available.` The exit code is 0
when the job completed or there was no job, and 1 when processing failed.
Without `--once` it keeps working through the queue, with the same
`--poll-seconds` and `--max-jobs` options as `run-worker`:

```bash
signalscope run-processing-worker
```

`DELETE /documents/<id>` also deletes the stored file of an imported document.
If the file cannot be deleted at that moment, it is recorded and can be
removed later:

```bash
signalscope cleanup-blobs --limit 100
```

It prints how many files it checked, deleted and could not delete. Files that
could not be deleted are tried again later, with a longer wait each time.

### Search

Processed text is split into chunks that PostgreSQL full text search can find:

```bash
curl "http://localhost:8000/search?q=climate+policy&limit=10"
```

Each result has the document, chunk and source IDs, the title, the URL, a
short plain text excerpt, a rank and the chunk metadata, which says for
example which PDF page the match came from. All words must match. `"quoted phrases"`,
`or` and `-word` work as on web search engines. `source_id` limits results to
one source.

### Semantic and hybrid search

Semantic search compares meaning instead of words. It uses embeddings: vectors
that an embedding model makes from each chunk. The database stores them with
the pgvector extension, so `compose.yaml` and CI run the
`pgvector/pgvector:pg17` image.

The model for now is `intfloat/multilingual-e5-small`. It handles many
languages and makes vectors with 384 dimensions. E5 models expect `query: `
before a search query and `passage: ` before stored text. SignalScope adds
these itself when it calls the model. They are never stored in document or
chunk text.

Each embedding records its provider, model and number of dimensions, and a
search only compares vectors from the same model. The E5 vectors have an HNSW
index, which keeps their search fast. Vectors from other models are compared
one by one.

#### Turn it on

The model runs on this machine. It is an optional extra, because it brings in
sentence-transformers and PyTorch. Install it and turn it on:

```bash
pip install -e ".[local-embeddings]"
export SIGNALSCOPE_LOCAL_EMBEDDINGS_ENABLED=true
```

The model is downloaded the first time it is used, not when SignalScope
starts. Check that it loads and works:

```bash
signalscope check-embedding-model
```

It embeds one query and one passage and prints the model, the number of
dimensions and how similar the two are. See
[docs/configuration.md](docs/configuration.md) for the device, batch size and
cache settings.

#### Embed chunks

The processing worker queues an embedding job for every new chunk. Chunks
that were made before embeddings were turned on have no job yet. Queue them
with:

```bash
signalscope queue-embeddings --limit 1000
```

It checks the chunks in a fixed order, skips those that already have a current
embedding or a waiting job, and prints how many it checked and queued.
`--document-id` limits it to one document. Then run the embedding worker:

```bash
signalscope run-embedding-worker --once
```

It embeds a batch of chunks in one model call and prints the model and how
many jobs completed, failed or were taken over by another worker. Without
`--once` it keeps running, with the same `--poll-seconds` and `--max-jobs`
options as the other workers, where each batch counts as one job.
`--batch-size` sets the most chunks per call.

See how far embedding has got:

```bash
curl "http://localhost:8000/embeddings/coverage"
curl "http://localhost:8000/embeddings/coverage?document_id=<document-id>"
```

It returns the number of chunks, how many have a current E5 embedding, how
many are waiting or failed, and the share that is done. It reads the database
only, so it works without the model installed.

#### Search

```bash
curl "http://localhost:8000/search/semantic?q=flood+risk&provider=sentence_transformers&model=intfloat/multilingual-e5-small"
curl "http://localhost:8000/search/hybrid?q=flood+risk&provider=sentence_transformers&model=intfloat/multilingual-e5-small"
```

`/search/semantic` embeds the query and returns the closest chunks with a
`similarity` between -1 and 1. `/search/hybrid` runs full text search and
vector search and merges both lists with Reciprocal Rank Fusion. Each result
shows its `lexical_rank`, its `vector_similarity` and the fused
`hybrid_score`. Chunks without embeddings can still be found by the full text
part. Both take `limit` and `source_id` like `/search`. They answer 503 when
local embeddings are off.

### Reranking

A reranker reads the query and each candidate chunk together and reorders the
candidates. SignalScope uses `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, a
multilingual model that runs on this machine. It needs its own extra and
switch, next to local embeddings:

```bash
pip install -e ".[local-reranking]"
export SIGNALSCOPE_LOCAL_RERANKING_ENABLED=true
```

```bash
curl "http://localhost:8000/search/reranked?q=flood+risk&limit=10"
```

`/search/reranked` runs hybrid search for three candidates per result and
lets the reranker order them by the full chunk text. Each result shows its
`hybrid_score` and its `reranker_score`. It answers 503 when local reranking or
local embeddings are off. The model is loaded, and downloaded the first time,
only when it first scores something.

### Research context

`POST /research/context` collects the evidence for a question, so that a
future answer step can cite it. It does not write answers or summaries, and it
does not call a language model.

```bash
curl -X POST http://localhost:8000/research/context \
  -H "Content-Type: application/json" \
  -d '{"query": "flooding in the harbour", "mode": "hybrid", "limit": 8}'
```

`mode` is `lexical`, `semantic`, `hybrid` (the default) or `reranked`, and
`source_id` limits the search to one source. The response lists the evidence
with IDs E1, E2 and so on, each with its document, chunk, title, URL, excerpt,
chunk metadata such as the PDF page, and the search scores. At most two chunks
come from one document, and overlapping or repeated chunks are left out.
`context_text` holds the same evidence as numbered blocks with the full chunk
text:

```text
[E1]
Title: Harbour Report
Page: 2
Text: Water flooded the harbour district.
```

The IDs only hold within one response. Reranked mode needs local reranking,
and the other modes, except lexical, need local embeddings.

### Research answers

`POST /research/answer` takes the same body as `/research/context` and is the
start of answers with citations. It collects the evidence, gives it to an
answer model as structured items and as numbered text blocks, and checks the
answer before returning it:

- every ID in `citation_ids` must belong to the evidence the model was given,
- the text must mark exactly those IDs, like `[E1]`,
- no ID may appear twice.

An answer that fails these checks is never returned; the request fails with
503 instead. The response maps each cited ID to its document, chunk, title,
URL and chunk metadata, such as the PDF page, so a reader never has to guess
which source an ID means. When no evidence is found, the model is not asked
and `answer` is `null`.

The answer model is `Qwen/Qwen3-4B-Instruct-2507`, run on this machine with
Transformers. It is optional and off by default, so the endpoint answers 503
until it is turned on:

```bash
pip install -e ".[local-answers]"
export SIGNALSCOPE_LOCAL_ANSWERS_ENABLED=true
signalscope check-answer-model
```

`check-answer-model` loads the model, downloading it the first time (several
gigabytes), answers one small question from one piece of evidence, runs the
same citation checks, and prints the provider, the model and the cited IDs.
`SIGNALSCOPE_LOCAL_ANSWER_DEVICE` picks where it runs, and
`SIGNALSCOPE_LOCAL_ANSWER_MAX_NEW_TOKENS` (default 512) caps the answer
length.

Then ask a question:

```bash
curl -X POST localhost:8000/research/answer   -H "Content-Type: application/json"   -d '{"query": "What flooded the harbour?", "mode": "hybrid", "limit": 5}'
```

Answers stay tied to the evidence. The model is only shown the question and,
for each piece of evidence, its ID, title and text. It is told to answer only
from that evidence and to return JSON with the text and the IDs it cites.
Generation is greedy, so the same evidence gives the same answer. Output that
is not exactly that JSON is rejected, and every answer goes through the
citation checks above before it is returned.

### Research sessions

A research session keeps a line of questions together. Create one with an
optional `title`, `retrieval_mode` (default `hybrid`) and `source_id`:

```bash
curl -X POST localhost:8000/research/sessions   -H "Content-Type: application/json" -d '{"title": "Harbour", "retrieval_mode": "hybrid"}'
curl -X POST localhost:8000/research/sessions/<id>/turns   -H "Content-Type: application/json" -d '{"question": "What flooded the harbour?"}'
```

Each turn searches again for its own question with the session's mode and
source, and is saved with its question, answer, citations and the evidence it
was answered from. `GET /research/sessions/{id}/turns` lists them in order.

`GET /research/sessions/{id}/export` returns the whole session: every turn
with its question, answer, citations and the evidence it was answered from.
It uses what each turn saved at the time and never searches again. Add
`?format=markdown` for a Markdown report instead of JSON:

```bash
curl "localhost:8000/research/sessions/<id>/export?format=markdown"
```

Earlier turns are given to the answer model as conversation context, so a
follow-up question can make sense. They are not evidence: their citation
markers are removed, and every answer must cite the evidence found for its own
turn, checked like any answer. Without an answer model, turns are still saved
with their evidence and no answer.

### Investigations

An investigation is a named collection of saved references to sources,
documents, events, event clusters, entities, claims and research sessions:

```bash
curl -X POST localhost:8000/investigations   -H "Content-Type: application/json" -d '{"title": "Harbour floods"}'
curl -X POST localhost:8000/investigations/<id>/items   -H "Content-Type: application/json"   -d '{"item_type": "event", "reference_id": "<event id>", "label": "Key event"}'
```

Each item keeps a small snapshot of the record as it was when it was saved,
such as a title, type and date, and never full document text. The snapshot is
not updated later, so the item stays useful if the record changes or is
deleted. `PATCH /investigations/{id}` changes the title, description or
status. A closed investigation is read only until it is opened again.

To keep a research session with an investigation, save it in one call:

```bash
curl -X POST localhost:8000/investigations/<id>/research-sessions/<session id>
```

The snapshot keeps the session title, search mode, source scope, number of
turns and time of the latest turn. Saving the same session again returns the
item saved before.

`GET /investigations/{id}/export` returns the investigation with all its
items grouped by type, as JSON or, with `?format=markdown`, as a Markdown
report. It shows the saved snapshots, not live data, and says for each item
whether the record still exists.

The same export is available from the command line:

```bash
signalscope export-investigation <id> --format markdown --output report.md
```

Without `--output` it prints to standard output. An existing file is only
replaced with `--overwrite`, and a file is written in full before it replaces
anything.

With authentication disabled, investigations are global: everyone who can
reach the API sees all of them. With authentication enabled, the investigation
routes need a bearer token, a new investigation needs the `organization_id` of
an organization you belong to, and you become its owner. Organization owners
and admins can do everything with the investigations of their organization.
Other members need an investigation role: `owner` (everything), `editor` (edit,
items and research sessions) or `viewer` (read and export). Investigations made
before accounts existed have no organization and only system admins see them.
The command line export is a local tool and is not checked.

Investigation roles are managed with these routes, which need authentication:

- `GET /investigations/{id}/members`: the collaborators, owners first.
- `POST /investigations/{id}/members`: add a member of the investigation's
  organization, with `{"user_id": "...", "role": "editor"}`. The role
  defaults to `viewer`.
- `PATCH /investigations/{id}/members/{user_id}`: change the role.
- `DELETE /investigations/{id}/members/{user_id}`: remove the collaborator.

Investigation owners and organization owners and admins may change them, also
while the investigation is closed. The last owner cannot be removed or demoted.

### Dashboard

Aggregate numbers for a future dashboard. They are counts only: no scores,
rankings or judgements of sources or events.

- `GET /dashboard/overview`: how many sources, documents, chunks, entities,
  claims, events, event clusters, research sessions and investigations exist,
  and how many ingestion, processing, embedding, entity, event and claim jobs
  are waiting or running.
- `GET /dashboard/sources?days=30&source_id=...`: documents stored and
  documents published per UTC day.
- `GET /dashboard/events?days=30&event_type=...&source_id=...`: events,
  event clusters, and clusters that two or more sources report, per UTC day
  by when they happened. Undated events are not counted.

`days` is 1 to 365. Every day is listed, with 0 for quiet days.

### Entities

SignalScope can find people, organizations, places, countries, cities,
products, events and dates in chunks with `urchade/gliner_multi-v2.1`, a
multilingual model that runs on this machine. It needs its own extra and
switch:

```bash
pip install -e ".[local-entities]"
export SIGNALSCOPE_LOCAL_ENTITIES_ENABLED=true
```

Queue the existing chunks, then run the worker:

```bash
signalscope queue-entities --limit 1000
signalscope run-entity-worker --once
```

`queue-entities` checks chunks in a fixed order, skips those already read or
waiting, and takes `--document-id` and `--limit`. `run-entity-worker` reads
one chunk per job and prints the job, its status and how many mentions it
found. Without `--once` it keeps running, with `--poll-seconds` and
`--max-jobs`, and stops cleanly on Ctrl+C. The model is loaded, and
downloaded the first time, only when a job needs it.

`GET /entities` lists the entities found, with `query` for part of a name,
`entity_type`, `limit` and `offset`. `GET /entities/{id}` shows one entity
with its mentions. Types are stored in lower case. Entities are linked by
normalized name and type only, so two people with the same name share one
entity.

### Events

SignalScope can read events, such as floods or elections, out of chunks with
`fastino/gliner2.5-multi-v1`, a multilingual GLiNER2 model that runs on this
machine. It needs its own extra and switch:

```bash
pip install -e ".[local-structured]"
export SIGNALSCOPE_LOCAL_STRUCTURED_ENABLED=true
```

Queue the existing chunks, then run the worker:

```bash
signalscope queue-events --limit 1000
signalscope run-event-worker --once
```

`queue-events` checks chunks in a fixed order, skips those already read or
waiting, and takes `--document-id` and `--limit`. It does not load the model.
`run-event-worker` reads one chunk per job and prints the job, its status and
how many events it found. Without `--once` it keeps running, with
`--poll-seconds` and `--max-jobs`, and stops cleanly on Ctrl+C. The model is
loaded, and downloaded the first time, only when a job needs it.

A date is only stored when its meaning is certain, such as `2026-03-04` or
`4 March 2026`. Other dates, such as `04/03/2026`, are kept as written in the
evidence metadata, and the event has no time.

`GET /events/{id}/link-suggestions?limit=10` lists events of the same type
that may report the same thing, ranked by the similarity of their local E5
embeddings (it needs local embeddings). These are suggestions for a person to
review, not links: the endpoint never changes clusters, and only the exact
linker puts events together.

`GET /events` lists events, with `event_type`, `occurred_from`,
`occurred_to`, `limit` and `offset`. `GET /events/{id}` shows one event with
its evidence. `GET /events/coverage` counts how many chunks the model has
read, optionally for one `document_id`, without loading the model.

### Timeline

Events from different documents that report the same thing can be linked
into one cluster. This first linker is strict: the event type and the title
must match after spaces and case are evened out, and when both events have a
time, they must fall on the same UTC day. There is no fuzzy matching yet.
The event worker links the events it finds right after it saves them. If
linking fails, the events stay saved but unclustered. Link them, and any events
from before automatic linking, with:

```bash
signalscope link-events --limit 1000
```

It prints how many events it checked and linked and how many clusters it
created. Running it again when everything is linked changes nothing.

`GET /timeline` lists the clusters in time order, newest first, or oldest
first with `order=oldest_first`. Clusters without a time come last. It takes
`occurred_from`, `occurred_to`, `event_type`, `source_id`, `limit` and
`offset`. Each item gives the title, type, time, and how many events,
sources and evidence rows back it, with the source names. The timeline only
describes what was reported; it does not rank events by importance.

Each timeline item has a `cluster_id`. `GET /event-clusters/{cluster_id}`
shows that cluster in detail: its member events (dated ones first, oldest
first) and, for each, where it was reported: document, chunk, source name,
model and chunk metadata such as the PDF page. It is read only; clusters are
formed by the exact linker and cannot be merged or split through the API.

### Source provenance

`GET /sources/{id}/provenance` shows what SignalScope has observed about one
source: how many documents it has, when they were stored and published, how
many distinct entities, claims and events were found in them, how many event
clusters those events belong to, how many of those clusters another source
also reports, and how many document revisions were kept.

These are observed provenance signals, not a credibility score. SignalScope
does not rate sources as reliable or unreliable and does not rank them against
each other. A high count only means more was observed.

`POST /sources/compare` with `{"source_ids": [...]}` (2 to 10 different
sources) shows the same profiles side by side, in the order given, plus how
many event clusters, entities and claims two or more of them have in common.
The comparison is descriptive: there is no score, winner or ranking.

Before trusting the model, check that it installs and runs on your machine.
This is for manual developer use: it loads the model and downloads it the
first time.

```bash
signalscope check-structured-model
```

It runs one structured extraction and one relation extraction on a short
built-in sentence and prints the provider, the model and `ok` for each. It
checks that the model loads and answers in the right shape, not that the
answers are correct; use `evaluate-extraction` for that. Tests never run it.

### Claims

The same GLiNER2 model and switch read claims: statements a text makes, such
as a statistic or a prediction. Each claim keeps the exact words it came from
and where they are in the chunk. SignalScope does not judge whether a claim is
true.

```bash
signalscope queue-claims --limit 1000
signalscope run-claim-worker --once
```

`queue-claims` and `run-claim-worker` work like `queue-events` and
`run-event-worker`, with the same options. The worker prints how many claims
it found in each chunk.

`GET /claims` lists claims, with `query`, `claim_type`, `limit` and `offset`.
`GET /claims/{id}` shows one claim with its evidence. `GET /claims/coverage`
counts how many chunks the model has read, like `GET /events/coverage`.

### Extraction evaluation

`signalscope evaluate-extraction data.json` scores event, claim and relation
extraction on a dataset of documents with hand-made answers, with the local
GLiNER2 model (it needs local structured extraction turned on and may download
the model the first time). `--mode` is `event`, `claim`, `relation` or `all`,
and `--json-output report.json` also writes the scores and, per document, what
was missed or extra.

A dataset file has `name`, `documents` (`key`, `text`, optional `language`),
and any of `events` (`document_key`, `event_type`, `title`, optional
`occurred_at`), `claims` (`document_key`, `claim_type`, `surface_text`,
`start_char`, `end_char`) and `relations` (`document_key`, `subject_text`,
`relation_type`, `object_text`, optional offsets).

Matching is exact, after normalizing case and spaces: events by type and title
(and UTC day when both have a date), claims by type and exact offsets,
relations by subject, type and object in the same direction. Each gold item
can be matched once. The command prints precision, recall and F1 and sets no
quality targets.

`--quality-gates gates.json` checks the scores against minimums that you
choose:

```json
{"event": {"precision": 0.7, "f1": 0.65}, "claim": {"f1": 0.7}}
```

Modes are `event`, `claim` and `relation`; metrics are `precision`, `recall`
and `f1`. Each minimum is printed as passed or missed, with the measured
value. A metric that is undefined, or a mode that did not run, counts as
missed. The exit code is 1 when any minimum is missed.

Relation extraction is experimental and for evaluation only. No relations are
stored and there is no knowledge graph.

### Retrieval evaluation

A retrieval dataset is a JSON file with documents, queries, and the documents
each query should find. [docs/examples/media-smoke.json](docs/examples/media-smoke.json)
shows the format. Score the search methods on it:

```bash
signalscope evaluate-retrieval docs/examples/media-smoke.json
signalscope evaluate-retrieval data.json --mode lexical --k 1,5,10
```

`--mode` is `lexical`, `semantic`, `hybrid`, `reranked` or `all` (the
default). Lexical mode needs no model. The other modes need local embeddings,
and the reranked mode needs local reranking too. In the `all` mode a missing
reranker skips the reranked mode, and the output says why. For each mode it
prints Recall@k, MRR@k and nDCG@k, and the mean, median (p50) and p95 search
time in milliseconds. The reranked mode also prints the reranker time
separately, because the reranker runs after the search.

`--json-output report.json` also writes the results to a JSON file: the
dataset, the k values, the models used, and for each mode the scores, the
scores of each query and the timings. It holds no vectors and no document
text, so reports from different runs can be compared.

`--quality-gates gates.json` checks the scores against minimums that you
choose, per mode:

```json
{"hybrid": {"recall@10": 0.8, "mrr@10": 0.5}, "reranked": {"ndcg@10": 0.6}}
```

The metrics are `recall@k`, `mrr@k` and `ndcg@k`, and each k must be in
`--k`. The command prints each minimum as passed or missed and exits with 1
when one is missed. SignalScope ships no minimums of its own, because the real
models have not been measured on a reference dataset yet.

The command needs `SIGNALSCOPE_DATABASE_URL`. It writes the dataset into the
database in one transaction, searches it with the normal search code, and
rolls the transaction back at the end, so nothing stays behind. Embeddings are
made before that transaction starts.

The scores describe one dataset. A small dataset, such as the example, only
shows that the pieces work. It does not show which method is better.

## Docker

Build and run the API image:

```bash
docker build -t signalscope .
docker run --rm -p 8000:8000 signalscope
```

Pass settings as environment variables, for example
`-e SIGNALSCOPE_LOG_LEVEL=DEBUG`. The same image can run migrations:

```bash
docker run --rm -e SIGNALSCOPE_DATABASE_URL=... signalscope alembic upgrade head
```
