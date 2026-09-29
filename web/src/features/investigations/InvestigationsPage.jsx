import { useCallback, useState } from "react";
import { Link } from "react-router";

import { useOrganization } from "../../app/useOrganization.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { Pager } from "../../components/Pager.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { formatTime } from "../../lib/format.js";
import { useResource } from "../../lib/useResource.js";

const PAGE_SIZE = 50;

/** Investigations of the active organization that the user may view. */
export function InvestigationsPage() {
  const { active, tenantApi } = useOrganization();
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const load = useCallback(
    () => tenantApi.get("/investigations", { query: { status, limit: PAGE_SIZE, offset } }),
    [tenantApi, status, offset],
  );
  const { data, error, loading, reload } = useResource(load);

  return (
    <>
      <PageHeading title="Investigations">
        <span className="muted">{active.name}</span>
      </PageHeading>
      <section className="panel" aria-labelledby="investigations-heading">
        <h2 id="investigations-heading">Investigations</h2>
        <label className="inline">
          Status
          <select
            value={status}
            onChange={(event) => {
              setOffset(0);
              setStatus(event.target.value);
            }}
          >
            <option value="">Open and closed</option>
            <option value="open">Open</option>
            <option value="closed">Closed</option>
          </select>
        </label>
        {loading && <Loading />}
        <ErrorMessage error={error} />
        {data && data.items.length > 0 && (
          <table>
            <thead>
              <tr>
                <th scope="col">Title</th>
                <th scope="col">Description</th>
                <th scope="col">Status</th>
                <th scope="col">Created</th>
                <th scope="col">Updated</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((investigation) => (
                <tr key={investigation.id}>
                  <td>
                    <Link to={`/investigations/${investigation.id}`}>{investigation.title}</Link>
                  </td>
                  <td className="wrap">{investigation.description ?? "-"}</td>
                  <td>{investigation.status}</td>
                  <td>{formatTime(investigation.created_at)}</td>
                  <td>{formatTime(investigation.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {data && (
          <Pager
            offset={offset}
            limit={PAGE_SIZE}
            count={data.items.length}
            total={data.total}
            onChange={setOffset}
            emptyText="No investigations yet."
          />
        )}
      </section>
      <CreateInvestigation onCreated={reload} />
    </>
  );
}

function CreateInvestigation({ onCreated }) {
  const { tenantApi } = useOrganization();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [created, setCreated] = useState(null);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setCreated(null);
    try {
      const body = { title, organization_id: tenantApi.organizationId };
      if (description.trim()) body.description = description.trim();
      const investigation = await tenantApi.post("/investigations", body);
      setTitle("");
      setDescription("");
      setCreated(investigation);
      onCreated();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="create-investigation">
      <h2 id="create-investigation">Start an investigation</h2>
      <form className="form" onSubmit={submit}>
        <label>
          Title
          <input
            required
            maxLength={200}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
        <label>
          Description (optional)
          <textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <ErrorMessage error={error} />
        {created && (
          <p role="status">
            {`"${created.title}" was started. `}
            <Link to={`/investigations/${created.id}`}>Open it</Link>
          </p>
        )}
        <button type="submit" disabled={busy}>
          {busy ? "Starting..." : "Start investigation"}
        </button>
      </form>
    </section>
  );
}
