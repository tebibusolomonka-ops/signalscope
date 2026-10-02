import { useCallback, useState } from "react";

import { useAuth } from "../../app/useAuth.js";
import { ConfirmAction } from "../../components/ConfirmAction.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { formatTime } from "../../lib/format.js";
import { useResource } from "../../lib/useResource.js";

const MIN_DAYS = 30;
const MAX_DAYS = 3650;

/**
 * Audit retention for one organization.
 *
 * Owners, admins and system admins see the policy and how many events it
 * would delete. Only system admins change the policy or run a cleanup. The
 * API decides; this only hides controls.
 */
export function Retention({ organizationId }) {
  const { api, user } = useAuth();
  const canChange = Boolean(user?.is_system_admin);
  const load = useCallback(async () => {
    const [policy, preview] = await Promise.all([
      api.get(`/organizations/${organizationId}/retention`),
      api.get(`/organizations/${organizationId}/retention/audit-preview`),
    ]);
    return { policy, preview };
  }, [api, organizationId]);
  const { data, error, loading, reload } = useResource(load);

  return (
    <section className="panel" aria-labelledby="retention-heading">
      <h2 id="retention-heading">Audit retention</h2>
      <p className="muted">
        How long this organization&apos;s security audit events are kept. By default they are kept
        indefinitely.
      </p>
      {loading && <Loading />}
      <ErrorMessage error={error} />
      {data && (
        <>
          <dl className="facts">
            <dt>Retention</dt>
            <dd>
              {data.policy.security_audit_days === null
                ? "Retained indefinitely"
                : `${data.policy.security_audit_days} days`}
            </dd>
            <dt>Events eligible for deletion</dt>
            <dd>{data.preview.eligible_count}</dd>
            <dt>Cutoff</dt>
            <dd>{data.preview.cutoff ? formatTime(data.preview.cutoff) : "-"}</dd>
          </dl>
          {canChange ? (
            <Controls
              organizationId={organizationId}
              policy={data.policy}
              eligible={data.preview.eligible_count}
              onChange={reload}
            />
          ) : (
            <p className="muted">Only system admins can change retention or delete events.</p>
          )}
        </>
      )}
    </section>
  );
}

function Controls({ organizationId, policy, eligible, onChange }) {
  const { api } = useAuth();
  const [mode, setMode] = useState(policy.security_audit_days === null ? "forever" : "days");
  const [days, setDays] = useState(String(policy.security_audit_days ?? 365));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function save(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const value = mode === "forever" ? null : Number(days);
      await api.put(`/organizations/${organizationId}/retention`, { security_audit_days: value });
      onChange();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  async function cleanup() {
    await api.post(`/organizations/${organizationId}/retention/audit-cleanup`, {
      limit: 1000,
      confirm: true,
    });
    onChange();
  }

  return (
    <>
      <form className="form-row" onSubmit={save} aria-label="Set retention">
        <label>
          Keep audit events
          <select value={mode} onChange={(event) => setMode(event.target.value)}>
            <option value="forever">Indefinitely</option>
            <option value="days">For a number of days</option>
          </select>
        </label>
        {mode === "days" && (
          <label>
            Days
            <input
              type="number"
              min={MIN_DAYS}
              max={MAX_DAYS}
              required
              value={days}
              onChange={(event) => setDays(event.target.value)}
            />
          </label>
        )}
        <button type="submit" disabled={busy}>
          Save policy
        </button>
      </form>
      <ErrorMessage error={error} />
      {policy.security_audit_days !== null && (
        <ConfirmAction
          label="Delete eligible events"
          question={`Delete up to 1000 of the ${eligible} events older than the cutoff? This cannot be undone.`}
          confirmLabel="Yes, delete events"
          onConfirm={cleanup}
        />
      )}
    </>
  );
}
