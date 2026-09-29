import { useCallback, useState } from "react";
import { Link, useNavigate } from "react-router";

import { useOrganization } from "../../app/useOrganization.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { Pager } from "../../components/Pager.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { formatTime } from "../../lib/format.js";
import { useResource } from "../../lib/useResource.js";
import { useSourceOptions } from "../sources/useSourceOptions.js";
import { RESEARCH_MODES } from "./modes.js";

const PAGE_SIZE = 50;

/** Research sessions of the active organization, and a form to start one. */
export function ResearchPage() {
  const { active, tenantApi, can } = useOrganization();
  const { sources, names } = useSourceOptions();
  const [offset, setOffset] = useState(0);
  const load = useCallback(
    () => tenantApi.get("/research/sessions", { query: { limit: PAGE_SIZE, offset } }),
    [tenantApi, offset],
  );
  const { data, error, loading } = useResource(load);

  return (
    <>
      <PageHeading title="Research">
        <span className="muted">{active.name}</span>
        <Link to="/research/new">Quick research</Link>
      </PageHeading>
      <section className="panel" aria-labelledby="sessions-heading">
        <h2 id="sessions-heading">Research sessions</h2>
        {loading && <Loading />}
        <ErrorMessage error={error} />
        {data && data.items.length > 0 && (
          <table>
            <thead>
              <tr>
                <th scope="col">Title</th>
                <th scope="col">Retrieval mode</th>
                <th scope="col">Sources searched</th>
                <th scope="col">Started</th>
                <th scope="col">Updated</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((session) => (
                <tr key={session.id}>
                  <td>
                    <Link to={`/research/${session.id}`}>
                      {session.title || "Untitled session"}
                    </Link>
                  </td>
                  <td>{session.retrieval_mode}</td>
                  <td>
                    {session.source_id ? (
                      <Link to={`/sources/${session.source_id}`}>
                        {names.get(session.source_id) ?? "One source"}
                      </Link>
                    ) : (
                      "All sources"
                    )}
                  </td>
                  <td>{formatTime(session.created_at)}</td>
                  <td>{formatTime(session.updated_at)}</td>
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
            emptyText="No research sessions yet."
          />
        )}
      </section>
      {can.contribute ? (
        <StartSession sources={sources} />
      ) : (
        <p className="muted">Your role in this organization can read sessions but not start one.</p>
      )}
    </>
  );
}

function StartSession({ sources }) {
  const { tenantApi } = useOrganization();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function submit(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body = {
      retrieval_mode: form.get("retrieval_mode"),
      organization_id: tenantApi.organizationId,
    };
    if (form.get("title").trim()) body.title = form.get("title").trim();
    if (form.get("source_id")) body.source_id = form.get("source_id");
    setBusy(true);
    setError(null);
    try {
      const session = await tenantApi.post("/research/sessions", body);
      navigate(`/research/${session.id}`);
    } catch (failure) {
      setError(failure);
      setBusy(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="start-session">
      <h2 id="start-session">Start a research session</h2>
      <p className="muted">
        Every question in a session searches this organization&apos;s documents with the mode and
        source chosen here.
      </p>
      <form className="form" onSubmit={submit}>
        <label>
          Title (optional)
          <input name="title" maxLength={200} />
        </label>
        <label>
          Retrieval mode
          <select name="retrieval_mode" defaultValue="hybrid">
            {RESEARCH_MODES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Source
          <select name="source_id" defaultValue="">
            <option value="">All sources</option>
            {sources.map((source) => (
              <option key={source.id} value={source.id}>
                {source.name}
              </option>
            ))}
          </select>
        </label>
        <ErrorMessage error={error} />
        <button type="submit" disabled={busy}>
          {busy ? "Starting..." : "Start session"}
        </button>
      </form>
    </section>
  );
}
