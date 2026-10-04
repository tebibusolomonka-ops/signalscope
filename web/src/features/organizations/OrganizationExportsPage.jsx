import { useCallback, useState } from "react";
import { Link, useParams } from "react-router";

import { useAuth } from "../../app/useAuth.js";
import { useOrganization } from "../../app/useOrganization.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { downloadBlob, exportFileName } from "../../lib/download.js";
import { formatTime } from "../../lib/format.js";
import { useResource } from "../../lib/useResource.js";

export function OrganizationExportsPage() {
  const { organizationId } = useParams();
  const { api, user } = useAuth();
  const { active, organizations } = useOrganization();
  const path = `/organizations/${organizationId}/exports`;
  const load = useCallback(
    async () => {
      const [exports, assets] = await Promise.all([api.get(path), api.get(`${path}/assets`)]);
      return { exports, assets };
    },
    [api, path],
  );
  const { data, error, loading, reload } = useResource(load);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [verifyingId, setVerifyingId] = useState(null);
  const [verification, setVerification] = useState(null);
  const verificationContext = `${organizationId}:${active?.id ?? ""}`;
  const organization = organizations.find((item) => item.id === organizationId);
  const canManage = Boolean(
    user?.is_system_admin || organization?.role === "owner" || organization?.role === "admin",
  );

  async function createExport() {
    setBusy(true);
    setActionError(null);
    try {
      await api.post(path);
      reload();
    } catch (failure) {
      setActionError(failure);
    } finally {
      setBusy(false);
    }
  }

  async function download(item) {
    setActionError(null);
    try {
      const blob = await api.getBlob(`${path}/${item.id}/download`);
      downloadBlob(exportFileName("organization", organizationId, "zip"), blob);
    } catch (failure) {
      setActionError(failure);
    }
  }

  async function verify(item) {
    setVerifyingId(item.id);
    setActionError(null);
    setVerification(null);
    try {
      const result = await api.post(`${path}/${item.id}/verify`);
      setVerification({ context: verificationContext, exportId: item.id, ...result });
    } catch (failure) {
      setActionError(failure);
    } finally {
      setVerifyingId(null);
    }
  }

  return (
    <>
      <PageHeading title="Organization exports">
        <Link to={`/organizations/${organizationId}`}>Organization settings</Link>
        <button type="button" onClick={createExport} disabled={busy}>
          {busy ? "Creating..." : "Create export"}
        </button>
      </PageHeading>
      <p className="muted">
        Portable ZIP archives contain this organization&apos;s tenant-scoped records. Stored binary
        files are referenced but not copied into the archive.
      </p>
      <p className="muted">
        An explicit expiry is shown below. Completed and failed exports may also be expired by the
        server&apos;s configured cleanup policy.
      </p>
      {loading && <Loading />}
      <ErrorMessage error={error ?? actionError} />
      {data && (
        <p>
          Export assets: {data.assets.asset_count} ({formatSize(data.assets.asset_bytes)}). Limits: {data.assets.max_assets} assets and {formatSize(data.assets.max_bytes)}.
        </p>
      )}
      {data && data.exports.length === 0 && <p>No exports yet.</p>}
      {data && data.exports.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Status</th>
                <th>Size</th>
                <th>Expiry</th>
                <th>Format</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {data.exports.map((item) => (
                <tr key={item.id}>
                  <td>{formatTime(item.created_at)}</td>
                  <td>{item.status}</td>
                  <td>{formatSize(item.size_bytes)}</td>
                  <td>{formatTime(item.expires_at)}</td>
                  <td>{item.format_version}</td>
                  <td>
                    {item.status === "completed" ? (
                      <div className="actions">
                        <button type="button" onClick={() => download(item)}>
                          Download
                        </button>
                        {canManage && (
                          <button
                            type="button"
                            className="secondary"
                            onClick={() => verify(item)}
                            disabled={verifyingId !== null}
                          >
                            {verifyingId === item.id ? "Verifying..." : "Verify"}
                          </button>
                        )}
                      </div>
                    ) : (
                      "-"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {verification?.context === verificationContext && (
        <section aria-label="Export verification">
          <h2>{verification.valid ? "Valid" : "Verification problems"}</h2>
          <p>Checked files: {verification.checked_files}</p>
          <p>Checked records: {verification.checked_records}</p>
          {!verification.valid && (
            <ul>
              {verification.problems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          )}
        </section>
      )}
    </>
  );
}

function formatSize(value) {
  if (value === null || value === undefined) return "-";
  if (value < 1024) return `${value} B`;
  return `${(value / 1024).toFixed(1)} KB`;
}
