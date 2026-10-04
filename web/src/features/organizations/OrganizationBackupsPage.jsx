import { useCallback, useState } from "react";
import { Link, useParams } from "react-router";

import { useAuth } from "../../app/useAuth.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { formatTime } from "../../lib/format.js";
import { useResource } from "../../lib/useResource.js";

export function OrganizationBackupsPage() {
  const { organizationId } = useParams();
  const { api, user } = useAuth();
  const base = `/organizations/${organizationId}`;
  const load = useCallback(async () => {
    const [policy, backups, memberships] = await Promise.all([
      api.get(`${base}/backup-policy`),
      api.get(`${base}/backups`),
      api.get("/organizations"),
    ]);
    const role = memberships.find((item) => item.organization.id === organizationId)?.role ?? null;
    return { policy, backups, role };
  }, [api, base, organizationId]);
  const { data, error, loading, reload } = useResource(load);
  const [actionError, setActionError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const canManage = Boolean(
    data && (user?.is_system_admin || data.role === "owner" || data.role === "admin"),
  );

  async function savePolicy(values) {
    setSaving(true);
    setActionError(null);
    try {
      await api.put(`${base}/backup-policy`, values);
      reload();
    } catch (failure) {
      setActionError(failure);
    } finally {
      setSaving(false);
    }
  }

  async function runBackup() {
    setRunning(true);
    setActionError(null);
    try {
      await api.post(`${base}/backups/run`);
      reload();
    } catch (failure) {
      setActionError(failure);
    } finally {
      setRunning(false);
    }
  }

  return (
    <>
      <PageHeading title="Organization backups">
        <Link to={`/organizations/${organizationId}`}>Organization settings</Link>
      </PageHeading>
      <p className="muted">
        Backups use the portable organization export format and count as successful only after
        verification.
      </p>
      {loading && <Loading />}
      <ErrorMessage error={error ?? actionError} />
      {data && (
        <>
          <PolicyForm
            key={`${data.policy.updated_at}:${data.policy.enabled}:${data.policy.frequency}`}
            policy={data.policy}
            disabled={!canManage || saving}
            onSave={savePolicy}
          />
          {canManage && (
            <p>
              <button type="button" onClick={runBackup} disabled={running}>
                {running ? "Running..." : "Run backup now"}
              </button>
            </p>
          )}
          <h2>Recent backups</h2>
          {data.backups.length === 0 ? (
            <p>No backups yet.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Result</th>
                    <th>Size</th>
                    <th>Error</th>
                  </tr>
                </thead>
                <tbody>
                  {data.backups.map((backup) => (
                    <tr key={backup.id}>
                      <td>{formatTime(backup.created_at)}</td>
                      <td>{backup.status === "completed" ? "Verified" : backup.status}</td>
                      <td>{formatSize(backup.size_bytes)}</td>
                      <td>{backup.safe_error ?? "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  );
}

function PolicyForm({ policy, disabled, onSave }) {
  const [enabled, setEnabled] = useState(policy.enabled);
  const [frequency, setFrequency] = useState(policy.frequency);
  const [retentionCount, setRetentionCount] = useState(String(policy.retention_count));
  const [includeAssets, setIncludeAssets] = useState(policy.include_assets);

  function submit(event) {
    event.preventDefault();
    onSave({
      enabled,
      frequency,
      retention_count: Number(retentionCount),
      include_assets: includeAssets,
    });
  }

  return (
    <section className="panel" aria-label="Backup policy">
      <form className="form" onSubmit={submit}>
        <label className="choice">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => setEnabled(event.target.checked)}
            disabled={disabled}
          />
          Scheduled backups enabled
        </label>
        <label>
          Frequency
          <select
            value={frequency}
            onChange={(event) => setFrequency(event.target.value)}
            disabled={disabled}
          >
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
          </select>
        </label>
        <label>
          Backups to keep
          <input
            type="number"
            min="1"
            max="100"
            value={retentionCount}
            onChange={(event) => setRetentionCount(event.target.value)}
            disabled={disabled}
          />
        </label>
        <label className="choice">
          <input
            type="checkbox"
            checked={includeAssets}
            onChange={(event) => setIncludeAssets(event.target.checked)}
            disabled={disabled}
          />
          Include binary assets
        </label>
        <dl className="facts">
          <dt>Last successful run</dt>
          <dd>{formatTime(policy.last_run_at)}</dd>
          <dt>Next run</dt>
          <dd>{formatTime(policy.next_run_at)}</dd>
        </dl>
        {!disabled && <button type="submit">Save backup policy</button>}
      </form>
    </section>
  );
}

function formatSize(value) {
  if (value === null || value === undefined) return "-";
  if (value < 1024) return `${value} B`;
  return `${(value / 1024).toFixed(1)} KB`;
}
