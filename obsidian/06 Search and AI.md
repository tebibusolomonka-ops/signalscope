# Search and AI

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
  have a date. No fuzzy matching.

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
