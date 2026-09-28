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
- **Investigations have no owner yet.** There is no auth, so investigations
  are global and internal. Ownership and sharing wait for an auth and
  organization design.
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
- **This vault is project memory**, updated at each five-commit checkpoint.
  The code wins when they disagree.
- **Simple English, no AI attribution** in code, docs and commits (AGENTS.md).
