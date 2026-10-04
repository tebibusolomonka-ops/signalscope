import { useCallback, useState } from "react";
import { Link, useParams } from "react-router";

import { useAuth } from "../../app/useAuth.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { formatTime } from "../../lib/format.js";
import { useResource } from "../../lib/useResource.js";

export function OrganizationDrillsPage() {
  const { organizationId } = useParams();
  const { api, user } = useAuth();
  const base = `/organizations/${organizationId}`;
  const load = useCallback(async () => {
    const [drills, memberships] = await Promise.all([
      api.get(`${base}/drills`),
      api.get("/organizations"),
    ]);
    const role = memberships.find((item) => item.organization.id === organizationId)?.role ?? null;
    const targets = memberships
      .map((item) => item.organization)
      .filter((organization) => organization.id !== organizationId);
    return { drills, role, targets };
  }, [api, base, organizationId]);
  const { data, error, loading, reload } = useResource(load);
  const [actionError, setActionError] = useState(null);
  const [running, setRunning] = useState(false);
  const [target, setTarget] = useState("");

  const canRun = Boolean(
    data && (user?.is_system_admin || data.role === "owner" || data.role === "admin"),
  );
  const canRestoreTest = Boolean(user?.is_system_admin);

  async function runDrill(payload) {
    setRunning(true);
    setActionError(null);
    try {
      await api.post(`${base}/drills`, payload);
      reload();
    } catch (failure) {
      setActionError(failure);
    } finally {
      setRunning(false);
    }
  }

  return (
    <>
      <PageHeading title="Disaster recovery">
        <Link to={`/organizations/${organizationId}`}>Organization settings</Link>
      </PageHeading>
      <p className="muted">
        A verification drill backs up this organization, verifies the archive and plans a restore
        without changing data. Restore tests require an empty target organization.
      </p>
      {loading && <Loading />}
      <ErrorMessage error={error ?? actionError} />
      {data && (
        <>
          {canRun && (
            <section className="panel" aria-label="Run a drill">
              <p>
                <button
                  type="button"
                  onClick={() => runDrill({ mode: "verification_only" })}
                  disabled={running}
                >
                  {running ? "Running..." : "Run verification drill"}
                </button>
              </p>
              {canRestoreTest && (
                <div className="form">
                  <label>
                    Restore-test target organization
                    <select value={target} onChange={(event) => setTarget(event.target.value)}>
                      <option value="">Select an empty organization</option>
                      {data.targets.map((organization) => (
                        <option key={organization.id} value={organization.id}>
                          {organization.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    onClick={() =>
                      runDrill({ mode: "restore_test", target_organization_id: target })
                    }
                    disabled={running || !target}
                  >
                    Run restore test
                  </button>
                  <p className="muted">
                    Restore tests only write into an empty target organization. They never create,
                    delete or overwrite an organization.
                  </p>
                </div>
              )}
            </section>
          )}
          <h2>Recent drills</h2>
          {data.drills.length === 0 ? (
            <p>No drills yet.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Started</th>
                    <th>Mode</th>
                    <th>Status</th>
                    <th>Finished</th>
                    <th>Restore</th>
                    <th>Error</th>
                  </tr>
                </thead>
                <tbody>
                  {data.drills.map((drill) => (
                    <tr key={drill.id}>
                      <td>{formatTime(drill.started_at)}</td>
                      <td>{drill.mode}</td>
                      <td>{drill.status}</td>
                      <td>{drill.finished_at ? formatTime(drill.finished_at) : "-"}</td>
                      <td>{drill.restore_id ? "yes" : "-"}</td>
                      <td>{drill.safe_error ?? "-"}</td>
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
