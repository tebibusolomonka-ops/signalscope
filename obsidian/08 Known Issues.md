# Known Issues

Open problems after batch 360 to 379. Remove an item when it is fixed.

## Events

- Empty-cluster cleanup can race with linking: if an empty cluster is deleted
  while a linker is adding an event to it, that link fails. The event stays
  unclustered and `link-events` repairs it.
- The linker only ever joins exact matches; near-duplicate titles stay in
  separate clusters. Semantic suggestions show them but do not merge them.
- Event date parsing is deliberately conservative: ISO dates and English month
  names only. Other dates are kept as text in evidence metadata.

## Models

- Real extraction quality (GLiNER, GLiNER2) has not been measured. The
  `evaluate-extraction` command exists, but there is no reference dataset yet
  and it has not been run with the real model.
- GLiNER2 relation extraction has an experimental provider but no real
  measurements. Its relation type list is a first guess.
- The GLiNER2 calls (`extract_json`, `extract_relations`, loading) were checked
  against the gliner2 2.0 source, not by running the real model.
- Real local models do not run in normal CI; only fakes do. The smoke check
  commands (`check-embedding-model`, `check-structured-model`,
  `check-answer-model`) are the way to try a real model, and none has been run
  on a real install yet.
- Evaluation report and bundle tests use fake providers. No measured real-model
  quality or latency results are stored in the repository.
- Relation benchmark tooling exists, but no real dataset result has been
  reviewed. Relation edges are not stored and persistence remains unimplemented.
- GLiNER2 extracts spans, so a claim's `text` usually repeats its quote.

## Research

- Two turns asked at the same time in one session get different sequence
  numbers, but the later one may not see the earlier one in its history.

## Investigations

- With auth off, investigations are global. With auth on, legacy
  investigations (no organization) are only reachable by system admins, and
  there is no command to move them into an organization.
- Removing someone from an organization leaves their collaborator rows; the
  roles stop counting but still show in the member list.
- An item whose record was deleted keeps its snapshot. Exports mark it with
  `current_reference_exists: false`; the item list itself does not.

## Operations

- A retried job keeps its attempt count, so a retried ingestion that fails
  again is not tried again automatically.
- Retention covers security audit events only.

## Dashboard

- "Pending" job counts include running jobs; stale running jobs whose lease
  expired are counted until a worker recovers them.
- Daily series use UTC days only; there is no local time zone option.

## Authentication

- Login throttling is a shared, fixed-window PostgreSQL limit. It is not an
  adaptive abuse-detection system.
- There is no password reset yet, only a change while signed in.
- There is no way to delete an organization or a user through the API.
- Invitations are shared by hand: there is no email sending.
- Clusters made before this batch that mix organizations keep no
  organization. Views hide the other organization's members, but such a
  cluster is only split by relinking its events by hand.
- Legacy sources are moved one at a time; there is no bulk move and no move
  between organizations.
- The saved investigation items from before this batch were not checked
  against organizations; they keep their old snapshots.
- Events without an organization (logins, user changes and throttle clearing)
  are only visible to system admins.
- `GET /auth/sessions` shows at most the 100 newest sessions; run
  `cleanup-auth-sessions` regularly.

## Admin web app

- It keeps the bearer token in sessionStorage, readable by scripts on the
  page. HttpOnly cookies, CSRF protection and a strict Content Security
  Policy are still to be reviewed before any public deployment.
- The API sends no CORS headers, so the app must be served from the API's
  origin (the development server proxies `/api`).
- Collaborator management offers members of the active organization; the
  API decides who may change roles and keeps the last owner.
- Research turns are not refreshed while the answer model is busy; reload the
  page to see a new turn completed elsewhere.
- Uploads are read into memory (at most 50 MB) before they are stored.
- The document page finds a focused chunk by paging its chunks (50 at a
  time, up to 2000); a chunk past that is reported as not found.

## Code

- The entity, event and claim queues, repositories, workers and coverage
  services are close copies of each other.

See [[10 Next Work]] for what is planned.
