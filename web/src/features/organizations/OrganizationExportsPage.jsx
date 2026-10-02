import { useCallback, useState } from "react";
import { Link, useParams } from "react-router";

import { useAuth } from "../../app/useAuth.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { downloadBlob, exportFileName } from "../../lib/download.js";
import { formatTime } from "../../lib/format.js";
import { useResource } from "../../lib/useResource.js";

export function OrganizationExportsPage() {
  const { organizationId } = useParams();
  const { api } = useAuth();
  const path = `/organizations/${organizationId}/exports`;
  const load = useCallback(() => api.get(path), [api, path]);
  const { data, error, loading, reload } = useResource(load);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(null);

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
      {loading && <Loading />}
      <ErrorMessage error={error ?? actionError} />
      {data && data.length === 0 && <p>No exports yet.</p>}
      {data && data.length > 0 && (
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
              {data.map((item) => (
                <tr key={item.id}>
                  <td>{formatTime(item.created_at)}</td>
                  <td>{item.status}</td>
                  <td>{formatSize(item.size_bytes)}</td>
                  <td>{formatTime(item.expires_at)}</td>
                  <td>{item.format_version}</td>
                  <td>
                    {item.status === "completed" ? (
                      <button type="button" onClick={() => download(item)}>
                        Download
                      </button>
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
    </>
  );
}

function formatSize(value) {
  if (value === null || value === undefined) return "-";
  if (value < 1024) return `${value} B`;
  return `${(value / 1024).toFixed(1)} KB`;
}
