# Next Work

Batch 251 to 270 is done; see [[02 Current State]]. Nothing below is built yet.

## Next batch

1. Run the real structured-extraction and answer-model smoke checks
   (`check-structured-model`, `check-answer-model`) on a suitable machine.
2. Build a small reference dataset, run `evaluate-extraction` with the real
   GLiNER2 model, and record the numbers here and in [[08 Known Issues]].
3. Decide from those numbers whether relation quality justifies storing
   knowledge-graph edges. No numbers, no edges.
4. Investigation collaboration only after an auth and organization design.
5. A frontend or admin dashboard over the aggregate APIs.

## Open follow-ups

- Reduce the copied queue and worker code for entities, events and claims.

Rules for this work: [[07 Decisions]].
