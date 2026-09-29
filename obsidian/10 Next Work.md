# Next Work

Batch 273 to 292, the identity and authorization foundation, is done: users,
passwords, sessions, the auth API, the bootstrap command, organizations,
investigation ownership, access policy and collaborators, session management
and cleanup, and the security audit log.

Current batch, 294 to 313: user administration, lifecycle, password
change, organization invitations and the security audit API (done); invitation
cleanup, admin session controls and an access summary (to do); then a small
React admin web app. Content data tenancy is deliberately not part of it.

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
