# Next Work

Batch 273 to 292, the identity and authorization foundation, is done: users,
passwords, sessions, the auth API, the bootstrap command, organizations,
investigation ownership, access policy and collaborators, session management
and cleanup, and the security audit log.

Batch 294 to 313 is done: the administration backend (users, lifecycle,
password change, invitations, audit API, cleanup, admin session controls,
access summary) and the first React admin web app.

Batch 314 to 333, organization content tenancy, is done: every content
route is scoped, event clusters and research sessions have organizations,
legacy sources can be assigned, and the web app has an active organization.

Batch 340 to 359 is done: the web app now covers the tenant research
workflow (sources, documents, file import, search, entities, claims, events,
clusters, source comparison, investigations with items and collaborators,
research sessions, one-shot research and exports), one organization at a
time. What stays as it was:

- Knowledge graph persistence remains deferred; no relation edges are stored.
- Real model evaluation (GLiNER2, E5, the reranker, Qwen) is still separate
  work on a suitable machine; no real numbers exist yet.
- Deployment is still same-origin: the API sends no CORS headers.
- The bearer token still lives in sessionStorage.

Batch 360 to 379 is done: organization operations, failed job recovery,
audit retention and research usability. The lease test no longer depends on
timing; the operations overview, failed job list, failed job retry (service,
API) and audit retention (policy, service, routes and cleanup command); the
operations, failed job and retention pages, an event page, and richer entity,
claim and event evidence; a reusable evidence and source reference UI; paged
research turns; tenant resource pickers that load every page; live ingestion
run refresh; and a start-session workflow that answers the first question.

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
