# Decisions

Decisions that should hold unless there is a clear reason to change them.

- **PostgreSQL queues, not Redis or Celery.** Jobs are rows claimed with
  `FOR UPDATE SKIP LOCKED`, with leases, heartbeats and ownership tokens. One
  database keeps operations simple. See [[05 Workers and Queues]].
- **pgvector is the vector database.** No separate vector store.
- **Blob store for binary files.** Raw bytes are not stored in PostgreSQL.
  Rows are written first; blobs are deleted after commit.
- **Local, lazy, optional models.** No hosted model APIs. Each model has its
  own extra and switch, is off by default, and never loads at import, startup
  or in unrelated commands.
- **Fake models in normal tests and CI.** No model downloads and no public
  network in tests.
- **Every provider result is validated** by a shared function before storage,
  whatever the model.
- **No subjective credibility score.** Source views show observed counts and
  dates only. No trust, reliability or ranking of sources.
- **Claims carry no truth judgement.**
- **Exact event linking is authoritative.** Automatic linking uses exact
  normalized type and title plus the same UTC day. It runs after the event
  worker commits, never during the model call, and a linking failure never
  fails a completed extraction job.
- **Semantic event links are suggestions only.** E5 similarity ranks
  candidates of the same type (and within 7 days when both are dated). There
  is no similarity threshold, and suggestions never change cluster membership.
- **Source comparison is descriptive.** Sources are shown in the order asked,
  with observed counts and shared items. No score, winner or ranking.
- **No persisted relation graph** until relation extraction has been
  evaluated on real data. The GLiNER2 relation provider is an evaluated
  candidate only: no worker runs it, no table stores relations, and no graph
  is built. The next decision on a graph must use real benchmark results from
  `evaluate-extraction`.
- **Relations are directional and matched exactly.** Subject, type and object
  must match in order after case and space normalization. No entity
  resolution in relation evaluation.
- **Answers must cite given evidence.** Citations are validated before an
  answer is returned; an answer that fails is not shown.
- **Conversation history is not evidence.** In research sessions, earlier
  questions and answers are context only, with their citation markers removed.
  Current factual answers still cite the evidence retrieved for the current
  turn.
- **Sessions work without a model.** A turn without an answer model is saved
  with its evidence and a null answer, instead of failing.
- **Turns are history.** Each turn stores the evidence the model saw at that
  time, including the chunk text, so it can be inspected later even if the
  documents change. No vectors or model internals are stored.
- **No quality targets without measurements.** Evaluation commands report
  numbers; any gates are user defined, and report only "passed" or "missed".
  An undefined metric or a mode that did not run misses its gate.
- **Clusters change only through the exact linker.** The cluster detail and
  suggestion routes are read only. Merging or splitting would need a future
  reviewed workflow.
- **Extraction is scored by exact matching.** Events match on normalized type
  and title (and UTC day when both have a date), claims on exact offsets and
  type. Matching is one to one, so repeated predictions do not help. No
  similarity matching in evaluation.
- **Investigation items are polymorphic saved references.** `reference_id`
  has no foreign key because it can point at seven tables. The service checks
  that the record exists when the item is saved, and stores a small snapshot
  (names, titles, types, dates; no content, vectors, files or prompts). The
  snapshot is never rewritten, so saved items keep their history.
- **Legacy investigations stay global.** Investigations made before accounts
  keep `organization_id` NULL; they are not moved into a made-up
  organization. With auth off everyone sees everything, as before. With auth
  on, only system admins reach them.
- **Investigation access.** System admins and organization owners and admins
  have full access. Other members need a collaborator role: owner (view, edit,
  delete, manage collaborators), editor (view, edit, items, research sessions)
  or viewer (view and export). A collaborator role counts only while the user
  is still a member of the organization. No view access answers 404, so
  investigations do not leak. The creator becomes the first owner, and there
  is always one owner, checked under a row lock on the investigation.
- **Closed investigations can be shared.** Collaborators can be changed while
  an investigation is closed, so it can be handed over or opened for reading
  without reopening it.
- **Logout-all includes the current session.** It is meant for a lost device
  or a leaked token, so nothing is left signed in.
- **Ended sessions are kept for a while.** Expired and revoked sessions stay
  `SIGNALSCOPE_AUTH_SESSION_RETENTION_DAYS` days (30) for inspection, then a
  bounded command deletes them. Active sessions are never deleted.
- **Audit events share the change's transaction.** An event is never written
  for a refused or failed change, and a change is never saved without its
  event. Details only take a fixed set of keys (IDs, roles, counts), so
  passwords, tokens and hashes cannot land there. Failed logins are not
  recorded yet. Deleting a user or organization keeps its events.
- **User administration is enforced in the service.**
  `UserAdministrationService` checks for an active system admin itself, so the
  rule does not depend on the routes. User creation goes through
  `AuthenticationService`, so hashing lives in one place.
- **There is always an active system admin.** Deactivation locks every active
  system admin row (in id order, before the target) and refuses to remove the
  last one, so two admins deactivating each other at once cannot both win.
- **Deactivation revokes sessions; reactivation does not restore them.**
- **A password change keeps the current session** and revokes the others, in
  the same commit. A wrong current password is 403 rather than 401, so a
  client does not treat it as a lost session.
- **Invitation tokens are stored as hashes only**, like session tokens. The
  raw token is shown once when the invitation is made. Invitations cannot
  make owners.
- **Invitation status is computed**, from accepted, revoked and expiry
  times, not stored as another mutable field. One pending invitation per
  address and organization; old rows stay as history.
- **Accepting needs the invited email.** The token alone is not enough: the
  signed in user's normalized email must match. Acceptance locks the
  invitation row and saves membership and accepted time together, so a token
  works once. An existing member gets 409, and the invitation stays pending.
- **Invalid invitation tokens share one answer** (404), like failed logins.
- **Audit reading is scoped by organization.** Organization owners and admins
  must name one organization they manage; results are never merged across
  organizations. Only system admins read events without an organization.
- **The source is the root of content ownership.** Only `sources` has an
  `organization_id` among normal content; documents, chunks, mentions and
  evidence belong to their source's organization and are filtered through
  it in SQL. Rows that span documents (event clusters, research sessions)
  get their own organization later in this batch.
- **Legacy content stays legacy.** Sources from before organizations keep
  `organization_id` NULL and are never assigned to a made-up organization.
  With auth on only system admins reach them; with auth off everything works
  as before.
- **One content policy.** `ContentAccessPolicy` gives a `ContentScope`:
  unrestricted (auth off), one organization, or legacy. Capabilities: viewer
  READ; member READ and CONTRIBUTE; admin and owner also MANAGE; system admins
  everything. READ covers reading and searching, CONTRIBUTE adding documents
  and research, MANAGE sources, schedules and ingestion runs.
- **Broad queries name one organization.** With auth on, lists and searches
  need `organization_id`. A system admin without it gets legacy content only,
  never every organization at once. Single records use the organization on
  their source, never one the caller sends. Content the caller may not see
  is 404, a missing role 403, a missing `organization_id` 422.
- **Scope filters run in SQL before any limit.** Search, vector search,
  hybrid fusion and reranking only ever see chunks in scope, so another
  organization's rows can take no place in a ranking, a limit or a count, and
  no other organization's text reaches a model. The HNSW scan keeps its
  iterative scan, so a filtered query still fills its limit.
- **Entities and claims stay shared rows.** One `Entity` or `Claim` row may be
  backed by mentions or evidence from several organizations. The row is not
  proof of access: in a scope it appears only with mentions or evidence in
  that scope, and its counts and details come from those only.
- **Events are seen through their evidence.** Cluster details and the
  timeline show only member events and evidence in scope, which also covers
  older clusters without an organization.
- **Event clusters never mix organizations.** A cluster has the organization
  of its events; the exact linker matches organization, type, title and day,
  so legacy events only join legacy clusters. An event whose evidence spans
  organizations is refused and left unclustered.
- **Legacy content moves in once, by command.** `assign-source-organization`
  only turns NULL into an organization, in one transaction, takes the
  source's events out of legacy clusters and links them again, and gives the
  source's source-limited legacy research sessions the same organization.
  It never moves content between organizations. Investigations stay as they
  were.
- **No combined view in the web app.** The admin app works in one active
  organization at a time, kept in sessionStorage; system admins pick one too.
- **Switching organization remounts content pages.** The content routes are
  keyed by the active organization, so no page, form or late answer of the
  old organization survives a switch.
- **File upload is a raw body, not a form.** `POST /documents/files` reads
  the file as the request body, stops at 50 MB, and reuses
  `FileImportService`, so no multipart library is needed and there is one
  import path. Only types with a parser are accepted.
- **Investigations are shown per organization.** The web app lists them with
  `organization_id` and treats an investigation of another organization as
  not found, even when the user may view it, so nothing of one organization
  appears under another.
- **Link suggestions stay advisory in the web app.** They load only when
  asked for, are labelled as suggestions, show the raw cosine similarity,
  and have no merge or link control.
- **The web app shows backend order and backend values.** Search results are
  never re-sorted, scores are labelled by what they are (lexical score,
  similarity, hybrid score, reranker score), and claims and entities carry no
  truth or quality labels.
- **Asking for ingestion queues it.** `POST /ingestion-runs` creates the run
  and its job together, like the scheduler, so a requested run is really
  picked up by a worker. Before, it only recorded a pending run.
- **Research sessions belong to an organization.** A session searches many
  documents, so it has its own `organization_id` and every turn searches only
  that organization's content, like one-shot context and answers.
- **Investigation items stay inside the organization.** With auth on, a
  saved record must belong to the investigation's organization: sources and
  documents by source, events and clusters by evidence, entities and claims by
  mentions or evidence there, research sessions by their organization. Another
  organization's ID answers like a missing record. Legacy investigations take
  legacy records only. Old snapshots are not rewritten.
- **Imports follow their source.** Documents added through
  `POST /documents`, `POST /documents/files` or `import-file` belong to their
  source's organization. `import-file --organization-id` refuses a source of another
  organization. Workers process every organization and never change
  ownership.
- **No new legacy content through the API.** With auth on, creating a source
  needs an organization, also for system admins.
- **Admin summaries are counts.** The access summary has no risk or trust
  scores and no ranking of users.
- **The admin app is React in JavaScript, not TypeScript**, with Vite, a
  small router and plain CSS. No component framework.
- **The bearer token lives in sessionStorage** for this first internal app:
  it is cleared with the browser session and is never in localStorage, URLs,
  logs or the page. A production web deployment should review HttpOnly
  cookie sessions, CSRF protection and a strong Content Security Policy.
- **Invitation tokens in the app live in component state only**, shown once.
- **The backend stays the authority.** The app may hide actions it expects
  to fail, but every rule is enforced by the API.
- **Exports replay history, not live data.** A research session export uses
  each turn's saved evidence and never searches again. An investigation export
  uses item snapshots; its only live value is whether a record still exists.
  Exports are returned or written by the caller, never stored on the server.
- **Dashboards are factual aggregates.** Counts and zero-filled UTC daily
  series from SQL aggregates. No credibility, trust, importance or political
  scores, and no source rankings.
- **No knowledge-graph edges yet.** Still deferred: the relation provider and
  evaluation exist, but no real benchmark result justifies storing edges.
- **Closed investigations are read only** until reopened: no edits, no item
  changes, no delete.
- **GLiNER2 cache folder.** gliner2 2.0 uses `cache_dir` for the config file
  only, so SignalScope downloads the model snapshot into the cache folder itself
  and loads from that folder.
- **Opaque server-side sessions, not JWT.** A login returns a random bearer
  token once; only its SHA-256 hash is stored, so sessions can be revoked and a
  database leak does not reveal tokens. Tokens, hashes, passwords and the
  Authorization header are never logged or put in errors.
- **Argon2id through pwdlib.** Library default costs in production; tests pass
  a cheaper hasher instead of weakening the defaults. The password policy is
  length only: 12 to 1024 characters.
- **One answer for every failed login.** Unknown email, wrong password and
  inactive account give the same 401, and an unknown email still runs a
  password check.
- **Auth is off by default.** `SIGNALSCOPE_AUTH_ENABLED=false` keeps every
  existing API open, as before. There is no self registration.
- **Organization roles.** Owners manage everyone; admins manage members and
  viewers only; members and viewers manage nobody. System admins may manage any
  organization as a recovery path. There is always at least one owner, checked
  under a row lock on the organization. Non-members get 404, not 403, so
  organizations do not leak. Members are added by user ID; there is no search
  by email, to avoid account discovery.
- **Accounts come from the command line.** The password is typed without echo
  or read from standard input, never passed as an option.
- **This vault is project memory**, updated at each five-commit checkpoint.
  The code wins when they disagree.
- **Simple English, no AI attribution** in code, docs and commits (AGENTS.md).
