# Next Work

Current batch: commits 273 to 292, the identity and authorization
foundation. Done: users, passwords, sessions, the auth API, the bootstrap
command, organizations, investigation ownership, the access policy and
collaborators. Still to do: session management, session cleanup, security
audit and an end to end test.

## Next batch

1. Run the real structured-extraction and answer-model smoke checks
   (`check-structured-model`, `check-answer-model`) on a suitable machine.
2. Build a small reference dataset, run `evaluate-extraction` with the real
   GLiNER2 model, and record the numbers here and in [[08 Known Issues]].
3. Decide from those numbers whether relation quality justifies storing
   knowledge-graph edges. No numbers, no edges.
4. Organization-scoped data tenancy, added gradually.
5. A frontend or admin dashboard over the aggregate APIs.

## Open follow-ups

- Reduce the copied queue and worker code for entities, events and claims.

Rules for this work: [[07 Decisions]].
