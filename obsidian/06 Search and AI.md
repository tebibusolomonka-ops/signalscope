# Search and AI

The web app links evidence to the exact passage: a search result and a
research citation's evidence card link to `/documents/<id>?chunk=<chunk-id>`,
which opens the document with that chunk highlighted. The chunk ID is not
secret and may be in the URL; chunk text and the bearer token never are.
Research citations also still focus the evidence card in place; opening it in
the document is a separate action.


Every model is optional, runs on the local machine, and is off by default.
Each has its own install extra and `SIGNALSCOPE_LOCAL_*` switch (see
`docs/configuration.md`). Models load lazily on first use. Normal tests use
fakes.

## Search

- **Lexical**: PostgreSQL full-text search on chunks (`websearch_to_tsquery`).
- **Semantic**: `intfloat/multilingual-e5-small` embeddings in pgvector, with
  an HNSW index. Extra: `local-embeddings`.
- **Hybrid**: lexical and semantic results fused with Reciprocal Rank Fusion
  (constant 60).
- **Reranked**: hybrid candidates rescored by an mMARCO multilingual MiniLM
  cross-encoder. Extra: `local-reranking`.
- `evaluate-retrieval` scores the modes on a dataset (Recall, MRR, nDCG) with
  optional user-defined quality gates.

## Extraction

- **Entities**: GLiNER `urchade/gliner_multi-v2.1`, a fixed label list, types
  in lower case. Extra: `local-entities`.
- **Events and claims**: GLiNER2 `fastino/gliner2.5-multi-v1` through one shared
  `Gliner2StructuredBackend` (`extract_json`). Extra: `local-structured`.
  Events keep a date only when it is certain. Claims keep exact quote offsets.
  Claims are statements; no truth judgement.
- **Event linking**: exact normalized type and title, same UTC day when both
  have a date. No fuzzy matching. Runs after the event worker commits;
  `link-events` repairs. Semantic suggestions (E5, same type, 7-day window)
  are for review only.
- **Relations (experimental)**: GLiNER2 native relation extraction over ten
  relation types (works_for, located_in, owns, acquired, founded, member_of,
  supports, opposes, announced, related_to). Pairs are (subject, object) and
  directional. Offsets only when the words appear once. Nothing is stored.
- **Extraction evaluation**: `evaluate-extraction` reports precision, recall
  and F1 for events, claims and relations with exact matching, and checks
  optional user-defined `--quality-gates`. `check-structured-model` is the
  manual smoke check for the real GLiNER2 install. Neither has been run with
  the real model yet, so there are no real numbers.
- **Evaluation evidence**: benchmark reports use a common versioned envelope.
  They can be compared factually, checked against user-defined profiles, and
  bundled with environment and gate evidence without running models.
  Release readiness lists imported report IDs, tasks, models, providers and
  dataset fingerprints, and says whether stored quality-gate evidence exists.
  It never runs a model or invents a metric.
- **Relation evaluation**: versioned datasets, exact micro and per-type metrics,
  optional confidence buckets, project-defined readiness gates and summaries
  provide evidence for human review. They make no persistence decision.
- **Semantic event links stay advisory**: `GET /events/{id}/link-suggestions`
  ranks candidates; only the exact linker changes clusters.

## Research answers

- Evidence comes from the search modes, at most two chunks per document, and
  gets IDs E1, E2 and so on.
- The answer model is `Qwen/Qwen3-4B-Instruct-2507` through Transformers,
  greedy decoding. Extra: `local-answers`.
- The model must return JSON `{text, citation_ids}`. Every answer is checked:
  cited IDs must be given, marked in the text, and not repeated. A failed check
  is a 503 without the model text.
- **Sessions**: the last 5 turns go to the model as "earlier conversation
  (context only, not evidence)", with citation markers removed. The current
  answer must cite the current turn's evidence.

Decisions behind this: [[07 Decisions]].
