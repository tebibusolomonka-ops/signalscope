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
- Concurrency rules (last owner, last system admin) have tests that run two
  sessions at once with `asyncio.gather`.
- Extraction quality is measured with `signalscope evaluate-extraction` on a
  local dataset, by hand, with the real model. It is not part of CI, and there
  are no built-in thresholds.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs the same checks on Python
3.12 with a PostgreSQL 17 + pgvector service, so all database tests run there.

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
