# Next Work

Current batch: commits 251 to 270. Done so far: the structured model smoke
check, extraction quality gates, the suggestions route, cluster detail and
saved investigations. Still to do in this batch: research session and
investigation exports, and factual dashboard data.

## After this batch

1. Build a small reference extraction dataset and run `evaluate-extraction`
   with the real GLiNER2 model. Record the numbers here and in
   [[08 Known Issues]].
2. Use those results to decide whether relation extraction is good enough to
   store. Only then consider entity-to-entity graph foundations.
3. A frontend or admin view over the dashboard data.

## Open follow-ups

- Reduce the copied queue and worker code for entities, events and claims.

Rules for this work: [[07 Decisions]].
