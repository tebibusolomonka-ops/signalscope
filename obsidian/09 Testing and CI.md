# Testing and CI

## Checks

```bash
pip install -e ".[dev]"
python scripts/check.py
```

This runs pytest, `ruff check`, `ruff format --check` and `mypy src` in order,
stops at the first failure, and checks that Alembic has one head.

## Tests

- `tests/unit`: no database or other service.
- `tests/integration`: database tests. They skip unless
  `SIGNALSCOPE_TEST_DATABASE_URL` is set, and its database name must end with
  `_test`.
- Shared fakes and helpers live directly in `tests/` (for example
  `fake_embeddings.py`, `fake_qwen.py`, `event_reports.py`).
- No test downloads a model or uses the public network. Optional libraries are
  replaced with fakes or made to fail on import.
- Evaluation manifest, report, comparison, gate and bundle tests use local
  fixtures and fake providers. Bundle tests verify stable order and checksums.
- Relation evaluation tests cover exact matching, per-type metrics, confidence
  buckets, user-defined gates and factual summaries without model downloads.
- `tests/integration/test_dashboard_end_to_end.py` checks that the dashboard,
  source comparison, timeline, research export and investigation export agree
  on one dataset.
- Auth tests use `tests/password_helpers.py` (test passwords and a cheap
  Argon2id hasher, so production costs stay unchanged), `tests/auth_helpers.py`
  (accounts, login, bearer headers) and the `auth_client` fixture, an app
  with auth on. `test_auth_end_to_end.py` covers the whole flow.
- `test_administration_end_to_end.py` runs the admin flow through the API
  and checks that no answer holds a password, hash or bearer token, and that
  the invitation token appears only in the answer that made it.
- `tests/tenancy_helpers.py` makes organizations A and B with one user per
  role, plus a system admin and an outsider, for organization content tests.
- `test_content_tenancy_audit.py` fills A and B with nearly the same content
  plus marker words, calls every content route as each side, and checks that
  no answer holds the other side's markers, IDs, names or counts. It also
  checks that dashboard counts match the lists.
- Database tests cannot run on the developer machine, so scoped queries are
  compiled locally with a fake session before pushing, which catches SQL
  shape errors such as ambiguous joins.
- Concurrency rules (last owner, last system admin) have tests that run two
  sessions at once with `asyncio.gather`.
- Extraction quality is measured with `signalscope evaluate-extraction` on a
  local dataset, by hand, with the real model. It is not part of CI, and there
  are no built-in thresholds.

## Web tests

`web/` uses Vitest with jsdom and React Testing Library. Tests talk to a fake
`fetch` (`src/test/fakeApi.js`), never a real API. `src/test/content.js`
and `organizations.js` build content answers and two organizations; every
content page has a test that switches organization while the new answer is
held back and checks that nothing of the old organization stays visible.
Lease tests never compare a 60 ms lease with the wall clock: recovery is
asked about a fixed moment between the observed old and extended lease ends,
so slow CI machines cannot change the result.
`tests/operations_helpers.py` adds jobs of any queue and state for an
organization; operations queries are also compiled in a unit test, so SQL
shape errors show up without PostgreSQL. `test_evidence_enrichment.py`
checks that entity, claim and event evidence carry the document title and
source name, from the requesting organization only.
`test_document_file_api.py` covers the upload route with file storage in a
temporary folder. `test_document_chunks_api.py` covers the paged chunk
navigation route and its tenant scope.
`ResearchNavigationFlow.test.jsx` is a web end-to-end test: it signs in,
searches, opens a result at its exact chunk, opens entity evidence, follows a
research citation and opens that evidence in the document, then switches
organization and checks that no marker of the first organization remains. `ResearchFlow.test.jsx` walks one organization's workflow
from sign in through a source, a document, search, an entity saved to an
investigation, a research follow-up with citations, and both exports.
`OrganizationSwitch.test.jsx` checks search, entities, claims, events,
investigations and research turns with the new organization's answers held
back. `src/test/downloads.js` records browser downloads. `AdminFlow.test.jsx` walks
through sign in, the dashboard, an organization, its invitations, the audit
log and sign out. Run `npm run lint`, `npm test -- --run` and
`npm run build` in `web/`.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs the same checks on Python
3.12 with a PostgreSQL 17 + pgvector service, so all database tests run there.

A second job, `web`, runs `npm ci`, lint, tests and build on Node 24.

On the current developer machine there is no local PostgreSQL, so database
tests only run in CI.

CI installs the newest allowed packages, which can be newer than a local
environment (for example SQLAlchemy 2.1 in CI and 2.0 locally, where `Select`
typing differs). Run mypy in a fresh environment before pushing typing-heavy
changes.

A session rollback expires every loaded object, even with
`expire_on_commit=False`. Do not read an ORM object after a failed call that
rolled back; keep plain values such as IDs, or commit instead of rolling back
when nothing failed.

## Workflow

Work is done in groups of five commits. Each commit is checked with targeted
tests and Ruff. After each group: `python scripts/check.py`, Alembic heads and
history, one normal push, and one CI run. A red run gets the smallest
corrective commit. History is never rewritten.

Paged-picker tests cover later Source and Investigation pages, deduplication,
server Source search and saving to a later Investigation. Source operation
tests use fake timers for active polling and verify that terminal runs stop
polling. Research start tests cover the direct request, no duplicate one-shot
request, navigation, errors and organization switches. Backend integration
coverage runs when `SIGNALSCOPE_TEST_DATABASE_URL` names a `_test` database.
