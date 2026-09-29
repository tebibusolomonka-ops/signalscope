# Architecture

One Python package, `src/signalscope`, with one PostgreSQL database. See
[[07 Decisions]] for why it is built this way.

## Layers

- **API** (`api/`): FastAPI app, routes, error handlers, request ID and logging
  middleware. Routes stay thin and call services. Model registries live on
  `app.state` and are built from settings at startup without loading models.
  Route list: [[04 API Map]].
- **Command line** (`cli.py`): ingestion, imports, backlogs, workers, model
  smoke checks and retrieval evaluation.
- **Domain and services** (`domain/`): one folder per area (sources, documents,
  ingestion, processing, search, entities, events, claims, blobs). Services own
  transactions. Repositories never commit.
- **PostgreSQL**: all state, including job queues and vectors (pgvector). Schema
  changes go through Alembic. See [[03 Database and Migrations]].
- **Blob store** (`storage/`): raw file bytes on the local disk, addressed by
  key. Database rows are written first; failed blob deletes are tracked as
  cleanup tasks.
- **Queues and workers** (`workers/` plus each area's job tables): PostgreSQL
  jobs with leases. See [[05 Workers and Queues]].
- **Parsers** (`parsing/`): text, JSON, HTML, PDF and DOCX, chosen by content
  type through a registry.
- **Search** (`domain/search/`, `embeddings/`, `reranking/`): lexical, semantic,
  hybrid and reranked search. See [[06 Search and AI]].
- **Extraction** (`entities/`, `extraction/`, `events/`, `claims/`): provider
  protocols, registries and local model wrappers. Every provider result goes
  through a shared validation function before it is stored.
- **Research** (`research/`): evidence retrieval, numbered context, answer
  generation behind a protocol, and citation validation. Research sessions
  (`domain/research/`) save each turn with the evidence it was answered from.
- **Users and authentication** (`domain/users/`, `api/auth.py`): accounts,
  Argon2id password credentials, and opaque login sessions. The `CurrentSession`
  dependency reads the bearer token. Off unless `SIGNALSCOPE_AUTH_ENABLED=true`.
- **Organizations** (`domain/organizations/`): organizations, memberships with
  roles, and `OrganizationService`, which holds the membership rules.
- **Investigations** (`domain/investigations/`): saved collections of
  references to records, each with a snapshot taken when it was saved.
  `InvestigationAccess` turns organization and collaborator roles into
  permissions; the services take the signed in user as the actor, or None
  when auth is off. `InvestigationMemberService` manages collaborators.
- **Administration** (`domain/users/administration.py`,
  `domain/organizations/invitations.py`, `access_summary.py`): user
  management, invitations and access counts. Each service checks its own
  permissions from the actor it is given.
- **Security audit** (`domain/audit/`): `SecurityAuditService` adds an event
  to the caller's transaction, so it commits with the change it describes.
  The auth, organization and collaborator services call it. Details are
  limited to a fixed set of keys (IDs and roles). `SecurityAuditQueryService`
  reads events for system admins and organization managers.
- **Content tenancy** (`domain/tenancy/`, `api/tenancy.py`): `ContentScope`
  (unrestricted when auth is off, one organization, or legacy content) turns
  into SQL conditions through the source, and `ContentAccessPolicy` decides
  the scope for a request and checks single resources. Routes get the
  policy and a read scope from `api/tenancy.py`. Normal content belongs
  to its source's organization; event clusters and research sessions, which
  span documents, have their own `organization_id`; entities and claims are
  shared rows seen through scoped mentions and evidence.
  `LegacySourceAssignmentService` moves a legacy source into an organization.
- **Dashboard** (`dashboard/`): aggregate counts and zero-filled UTC daily
  series, built with SQL aggregates.
- **Relations** (`relations/`): relation extraction interface and an
  experimental GLiNER2 provider, used only by evaluation. Nothing is stored.
- **Evaluation** (`evaluation/`): retrieval evaluation, and event, claim and
  relation extraction evaluation (`evaluation/extraction/`), against local
  datasets.

## Admin web app

`web/` is a React app in plain JavaScript (no TypeScript), built with Vite
and tested with Vitest and React Testing Library. It is internal and
admin-focused.

- `src/lib/`: `api.js` (a fetch wrapper that sends JSON and the bearer
  token, and turns error answers into `ApiError`), `config.js`
  (`VITE_SIGNALSCOPE_API_URL`, default `/api`), `session.js` (the token in
  sessionStorage) and `useResource.js` (load, error and reload state).
- `src/app/`: routes, the shell with navigation and an active organization
  picker, `AuthProvider` (restores a session with `GET /auth/me`, logs in and
  out), `RequireAuth`, and `OrganizationProvider` (the user's organizations
  and the active one, remembered in sessionStorage).
- `src/lib/tenantApi.js`: a client that adds `organization_id` to content
  calls. Sign in, user, organization and security calls use the plain client.
- `src/app/RequireOrganization.jsx`: content pages sit under this route.
  Without an active organization it explains that one must be chosen (also
  for system admins). It keys the pages by the organization, so switching
  unmounts them and their data before the new organization loads.
- `src/lib/capabilities.js`: read, contribute and manage hints from the
  active role, only for hiding buttons.
- `src/features/`: auth, dashboard, organizations, invitations, users and
  security pages, and the content workspaces: sources (list, create, detail,
  provenance, ingestion and schedule, delete), documents (filtered list,
  detail with text and revisions, delete, file import), search (four modes,
  query kept in the URL with its organization), entities and claims (lists
  and evidence), the event timeline and cluster pages (with on-demand,
  advisory link suggestions), source comparison, investigations (list,
  create, detail with saved items, collaborators, close, reopen, delete),
  research sessions (list, start, multi-turn conversation with citations and
  a separate evidence panel) and one-shot research (`/research/new`). A
  shared `SaveToInvestigation` control saves sources, documents, events,
  clusters, entities, claims and research sessions into an open
  investigation of the active organization. `ExportActions` downloads the
  backend's JSON and Markdown exports in the browser, named by record ID.
- The development server proxies `/api` to the API, which has no CORS
  support; production must serve both from one origin.
- The API decides every permission. The app may hide actions, but it never
  holds role rules that act as a security boundary.

## Patterns

- Optional libraries are imported inside a loader, so SignalScope runs without
  them. A missing library becomes a clear 503 or command error.
- Models load lazily behind an asyncio lock and run in a worker thread.
- A provider is chosen by (provider name, model name) from an explicit registry.
  A missing provider is a service-unavailable error.
- Workers commit the job claim before the model runs, so no transaction is open
  during inference.
