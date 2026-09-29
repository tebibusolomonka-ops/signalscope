import { useCallback, useState } from "react";
import { Link } from "react-router";

import { useOrganization } from "../../app/useOrganization.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { Pager } from "../../components/Pager.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { formatTime } from "../../lib/format.js";
import { useResource } from "../../lib/useResource.js";
import { scheduleText } from "./sourceText.js";

const PAGE_SIZE = 50;
// The source types of the API. Web and RSS sources need a URL.
const SOURCE_TYPES = ["web", "rss", "upload", "api"];
const NEEDS_URL = new Set(["web", "rss"]);

/** Sources of the active organization. The list has no filters in the API, only pages. */
export function SourcesPage() {
  const { active, tenantApi, can } = useOrganization();
  const [offset, setOffset] = useState(0);
  const load = useCallback(
    () => tenantApi.get("/sources", { query: { limit: PAGE_SIZE, offset } }),
    [tenantApi, offset],
  );
  const { data, error, loading, reload } = useResource(load);

  return (
    <>
      <PageHeading title="Sources">
        <span className="muted">{active.name}</span>
      </PageHeading>
      <section className="panel" aria-labelledby="sources-heading">
        <h2 id="sources-heading">Sources</h2>
        {loading && <Loading />}
        <ErrorMessage error={error} />
        {data && data.items.length > 0 && <SourceTable sources={data.items} />}
        {data && (
          <Pager
            offset={offset}
            limit={PAGE_SIZE}
            count={data.items.length}
            total={data.total}
            onChange={setOffset}
            emptyText="This organization has no sources yet."
          />
        )}
      </section>
      {can.manage && <CreateSource onCreated={reload} />}
    </>
  );
}

function SourceTable({ sources }) {
  return (
    <table>
      <thead>
        <tr>
          <th scope="col">Name</th>
          <th scope="col">Type</th>
          <th scope="col">URL</th>
          <th scope="col">Scheduled ingestion</th>
          <th scope="col">Next ingestion</th>
          <th scope="col">Updated</th>
        </tr>
      </thead>
      <tbody>
        {sources.map((source) => (
          <tr key={source.id}>
            <td>
              <Link to={`/sources/${source.id}`}>{source.name}</Link>
            </td>
            <td>{source.type}</td>
            <td className="wrap">{source.url ?? "-"}</td>
            <td>{scheduleText(source)}</td>
            <td>{source.ingestion_enabled ? formatTime(source.next_ingestion_at) : "-"}</td>
            <td>{formatTime(source.updated_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function CreateSource({ onCreated }) {
  const { tenantApi } = useOrganization();
  const [type, setType] = useState("rss");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [created, setCreated] = useState(null);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setCreated(null);
    try {
      const body = { type, name, organization_id: tenantApi.organizationId };
      if (url.trim()) body.url = url.trim();
      const source = await tenantApi.post("/sources", body);
      setName("");
      setUrl("");
      setCreated(source);
      onCreated();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="create-source">
      <h2 id="create-source">Add a source</h2>
      <form className="form" onSubmit={submit}>
        <label>
          Type
          <select value={type} onChange={(event) => setType(event.target.value)}>
            {SOURCE_TYPES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label>
          Name
          <input
            required
            maxLength={200}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label>
          {NEEDS_URL.has(type) ? "URL" : "URL (optional)"}
          <input
            type="url"
            required={NEEDS_URL.has(type)}
            value={url}
            onChange={(event) => setUrl(event.target.value)}
          />
        </label>
        <ErrorMessage error={error} />
        {created && <p role="status">{`Source "${created.name}" was added.`}</p>}
        <button type="submit" disabled={busy}>
          {busy ? "Adding..." : "Add source"}
        </button>
      </form>
    </section>
  );
}
