# Known Issues

Open problems as of commit 298. Remove an item when it is fixed.

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
- Relation edges are still not stored: no real relation benchmark exists to
  justify them.
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

## Dashboard

- "Pending" job counts include running jobs; stale running jobs whose lease
  expired are counted until a worker recovers them.
- Daily series use UTC days only; there is no local time zone option.

## Authentication

- Login has no rate limit or lockout yet.
- There is no password reset yet, only a change while signed in.
- There is no way to delete an organization or a user through the API.
- Invitations have a table but no service or API yet.
- Only investigations and organizations are protected; other APIs stay open
  even when auth is on, until data tenancy is designed.
- The saved records an investigation points at are not checked against the
  organization: any record ID can be saved and its snapshot read.
- Audit events have no read API or retention rule yet, and failed logins are
  not recorded.
- `GET /auth/sessions` shows at most the 100 newest sessions; run
  `cleanup-auth-sessions` regularly.

## Code

- The entity, event and claim queues, repositories, workers and coverage
  services are close copies of each other.

See [[10 Next Work]] for what is planned.
