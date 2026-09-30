import { useCallback, useState } from "react";

import { useAuth } from "../../app/useAuth.js";
import { useOrganization } from "../../app/useOrganization.js";
import { ConfirmAction } from "../../components/ConfirmAction.jsx";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { formatTime } from "../../lib/format.js";
import { useResource } from "../../lib/useResource.js";

/**
 * Security audit retention for the active organization.
 *
 * Owners, admins and system admins see how long events are kept and how many
 * a cleanup would remove now. Only system admins may change the number of days
 * or run a cleanup, and a cleanup asks before it deletes.
 */
export function RetentionPage() {
  const { active, tenantApi, can } = useOrganization();
  const { user } = useAuth();
  const canEdit = Boolean(user?.is_system_admin);
  const load = useCallback(
    () => tenantApi.get("/security/audit/retention/preview"),
    [tenantApi],
  );
  const { data, error, loading, reload } = useResource(load);

  if (!can.manage) {
    return (
      <>
        <PageHeading title="Audit retention">
          <span className="muted">{active.name}</span>
        </PageHeading>
        <p className="muted">Audit retention is for organization owners and admins.</p>
      </>
    );
  }

  async function runCleanup() {
    await tenantApi.post("/security/audit/retention/cleanup", {});
    reload();
  }

  return (
    <>
      <PageHeading title="Audit retention">
        <span className="muted">{active.name}</span>
      </PageHeading>
      <section className="panel" aria-labelledby="retention-heading">
        <h2 id="retention-heading">Security audit retention</h2>
        <p className="muted">
          How long this organization keeps its security audit events. Kept for ever means events are
          never removed.
        </p>
        {loading && <Loading />}
        <ErrorMessage error={error} />
        {data && (
          <>
            <dl className="facts">
              <dt>Retention</dt>
              <dd>
                {data.security_audit_days === null
                  ? "Kept for ever"
                  : `${data.security_audit_days} days`}
              </dd>
              <dt>Events past the policy</dt>
              <dd>
                {data.deletable_count} of {data.total_count}
              </dd>
              <dt>Cutoff</dt>
              <dd>{data.security_audit_days === null ? "-" : formatTime(data.cutoff)}</dd>
            </dl>
            {canEdit ? (
              <Editor
                api={tenantApi}
                current={data.security_audit_days}
                deletable={data.deletable_count}
                onChange={reload}
                onCleanup={runCleanup}
              />
            ) : (
              <p className="muted">Only system admins can change the policy or run a cleanup.</p>
            )}
          </>
        )}
      </section>
    </>
  );
}

function Editor({ api, current, deletable, onChange, onCleanup }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function save(event) {
    event.preventDefault();
    const raw = new FormData(event.currentTarget).get("days").trim();
    setBusy(true);
    setError(null);
    try {
      await api.put("/security/audit/retention", {
        security_audit_days: raw === "" ? null : Number(raw),
      });
      onChange();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <form className="form-row" aria-label="Set retention" onSubmit={save}>
        <label>
          Keep for (days)
          <input
            name="days"
            type="number"
            min="30"
            max="3650"
            defaultValue={current ?? ""}
            placeholder="Leave empty to keep for ever"
          />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? "Saving..." : "Save policy"}
        </button>
      </form>
      <ErrorMessage error={error} />
      <ConfirmAction
        label="Run cleanup"
        question={`Delete ${deletable} audit events past the policy? This cannot be undone.`}
        confirmLabel="Delete events"
        onConfirm={onCleanup}
      />
    </>
  );
}
