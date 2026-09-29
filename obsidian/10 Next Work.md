# Next Work

Batch 273 to 292, the identity and authorization foundation, is done: users,
passwords, sessions, the auth API, the bootstrap command, organizations,
investigation ownership, access policy and collaborators, session management
and cleanup, and the security audit log.

Batch 294 to 313 is done: the administration backend (users, lifecycle,
password change, invitations, audit API, cleanup, admin session controls,
access summary) and the first React admin web app.

Next planned area: design and implement organization-scoped content tenancy
across sources, documents, search, entities, events, claims, research and
dashboards as one coordinated security boundary; then expand the admin
frontend over investigations and research sessions.

## Next batch

1. Run the real structured-extraction and answer-model smoke checks
   (`check-structured-model`, `check-answer-model`) on a suitable machine.
2. Build a small reference dataset, run `evaluate-extraction` with the real
   GLiNER2 model, and record the numbers here and in [[08 Known Issues]].
3. Decide from those numbers whether relation quality justifies storing
   knowledge-graph edges. No numbers, no edges.
4. Review the web session model (HttpOnly cookies, CSRF, CSP) before any
   public deployment.

## Open follow-ups

- Reduce the copied queue and worker code for entities, events and claims.

Rules for this work: [[07 Decisions]].
