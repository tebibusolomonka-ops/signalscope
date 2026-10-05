# Release readiness runbook

These checks provide factual evidence for a release decision. They do not
replace operator review and do not make a security, compliance or recovery
guarantee.

## Before the review

1. Run `signalscope validate-production-config` and resolve every error.
2. Run `signalscope startup-preflight --json`. Review database, storage, queues,
   build metadata and configuration findings.
3. Run `signalscope check-migration-compatibility --json`. Apply migrations by
   the normal deployment process when the database is behind; this command
   never applies them.
4. Run `signalscope validate-deployment deployment-profile.json --json`.
5. After validation passes, write the immutable evidence manifest with
   `signalscope create-release-candidate --profile deployment-profile.json
   --output release-candidate.json`.

## Backup and disaster recovery

- Verify a local archive with `signalscope verify-organization-export FILE.zip`.
  For a managed backup, confirm the latest run is completed and has a SHA-256.
- Run a non-mutating verification drill with `signalscope
  run-disaster-recovery-drill ORGANIZATION_ID --mode verification-only`.
- Use a restore-test only when the review requires it. Prepare a separate empty
  organization, map archived users explicitly, then run `--mode restore-test
  --target-organization TARGET_ID`. Never use the source organization as the target.
- For an emergency restore, preserve the source archive, verify it, generate a
  restore plan, resolve every conflict and mapping, restore only into the
  approved empty target, then validate counts and access before routing traffic.

## Diagnostics, rollback and escalation

- Create a redacted diagnostics archive with `signalscope
  create-support-bundle --output support.zip`. Review it before sharing.
- Stop and escalate when migration state is unknown, required storage is
  unavailable, a required backup or drill is missing or stale, or any acceptance
  requirement is missed.
- Roll back with the deployment system's established application rollback.
  Do not downgrade the database automatically. Escalate schema rollback to the
  database owner and preserve the failed release evidence.

## Final evidence

Run:

```bash
signalscope run-acceptance --profile acceptance.json \
  --organization-id ORGANIZATION_ID \
  --deployment-profile deployment-profile.json --json

signalscope release-readiness --profile acceptance.json \
  --organization-id ORGANIZATION_ID \
  --deployment-profile deployment-profile.json --json
```

Review requirements met and missed, warnings, manual checks, backup and drill
IDs and timestamps, migration state, deployment validation, pilot observations
and imported model-evaluation references. The commands are read-only and do not
run models or operational actions.
