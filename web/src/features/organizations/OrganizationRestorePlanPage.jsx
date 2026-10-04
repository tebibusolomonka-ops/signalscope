import { useState } from "react";
import { useParams } from "react-router";

import { useAuth } from "../../app/useAuth.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage } from "../../components/Status.jsx";

export function OrganizationRestorePlanPage() {
  const { organizationId } = useParams();
  const { api, user } = useAuth();
  const [file, setFile] = useState(null);
  const [plan, setPlan] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  if (!user?.is_system_admin) {
    return <p>You do not have permission to plan restores.</p>;
  }

  async function submit(event) {
    event.preventDefault();
    if (!file) {
      return;
    }
    setBusy(true);
    setError(null);
    setPlan(null);
    try {
      setPlan(
        await api.upload(
          `/organizations/${organizationId}/restore-plan`,
          file,
          "application/zip",
        ),
      );
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeading title="Restore planning" />
      <p className="muted">Dry run. No data will be changed.</p>
      <form onSubmit={submit}>
        <label>
          Organization export ZIP
          <input
            type="file"
            accept="application/zip,.zip"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <button type="submit" disabled={!file || busy}>
          {busy ? "Planning..." : "Plan restore"}
        </button>
      </form>
      <ErrorMessage error={error} />
      {plan && (
        <section aria-label="Restore plan">
          <p>Format version: {plan.archive.format_version}</p>
          <p>Checked files: {plan.archive.checked_files}</p>
          <p>Checked records: {plan.archive.checked_records}</p>
          <p>Assets: {plan.inventory.asset_count}</p>
          <h2>Record counts</h2>
          <dl>
            {Object.entries(plan.inventory.counts).map(([name, count]) => (
              <div key={name}>
                <dt>{name}</dt>
                <dd>{count}</dd>
              </div>
            ))}
          </dl>
          <PlanList title="Conflicts" values={plan.conflicts} />
          <PlanList title="Warnings" values={plan.warnings} />
          <PlanList title="Unresolved users" values={plan.unresolved_user_ids} />
        </section>
      )}
    </>
  );
}

function PlanList({ title, values }) {
  return (
    <section>
      <h2>{title}</h2>
      {values.length ? (
        <ul>
          {values.map((value) => (
            <li key={value}>{value}</li>
          ))}
        </ul>
      ) : (
        <p>None.</p>
      )}
    </section>
  );
}
