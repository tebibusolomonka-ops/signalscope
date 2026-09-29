# Next Work

Batch 273 to 292, the identity and authorization foundation, is done: users,
passwords, sessions, the auth API, the bootstrap command, organizations,
investigation ownership, access policy and collaborators, session management
and cleanup, and the security audit log.

Batch 294 to 313 is done: the administration backend (users, lifecycle,
password change, invitations, audit API, cleanup, admin session controls,
access summary) and the first React admin web app.

Current batch, 314 to 333: organization content tenancy. Done: the result
warning fix, source ownership, the content policy, and scoped sources,
documents, search, entities, claims, events, coverage, timeline,
provenance, comparison, dashboard, research, investigation references and
file import. To do: organization-owned event clusters, the legacy assignment
command, a route audit and the web organization context.

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
