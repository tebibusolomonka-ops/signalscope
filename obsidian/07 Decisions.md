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
  normalized type and title plus the same UTC day. Semantic linking, when it
  comes, starts as suggestions only and never changes clusters by itself.
- **No persisted relation graph** until relation extraction has been
  evaluated on real data.
- **Answers must cite given evidence.** Citations are validated before an
  answer is returned; an answer that fails is not shown.
- **No quality targets without measurements.** Evaluation commands report
  numbers; any gates are user defined.
- **Simple English, no AI attribution** in code, docs and commits (AGENTS.md).
