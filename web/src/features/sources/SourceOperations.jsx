import { useCallback, useEffect, useState } from "react";

import { useOrganization } from "../../app/useOrganization.js";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { formatTime } from "../../lib/format.js";
import { useResource } from "../../lib/useResource.js";

const RUNS_SHOWN = 10;
const REFRESH_INTERVAL = 5000;
const TERMINAL_STATUSES = new Set(["completed", "failed"]);
const MAX_INTERVAL_MINUTES = 7 * 24 * 60;
// Only these types have a worker adapter that fetches content.
const FETCHED_TYPES = new Set(["web", "rss"]);

/**
 * Ingestion of one source: queue a run now, the schedule, and recent runs.
 *
 * Buttons are only offered to roles that manage sources; the API decides.
 */
export function SourceOperations({ source, onSourceChange }) {
  const { tenantApi, can } = useOrganization();
  const fetched = FETCHED_TYPES.has(source.type);
  const loadRuns = useCallback(async () => {
    const query = { source_id: source.id, limit: RUNS_SHOWN };
    // The API lists runs oldest first, so the newest are on the last page.
    const first = await tenantApi.get("/ingestion-runs", { query });
    if (first.total <= RUNS_SHOWN) return first;
    return tenantApi.get("/ingestion-runs", {
      query: { ...query, offset: first.total - RUNS_SHOWN },
    });
  }, [tenantApi, source.id]);
  const runs = useResource(loadRuns);

  useEffect(() => {
    if (!runs.data?.items.some((run) => !TERMINAL_STATUSES.has(run.status))) return undefined;
    const timer = window.setTimeout(runs.reload, REFRESH_INTERVAL);
    return () => window.clearTimeout(timer);
  }, [runs.data, runs.reload]);

  return (
    <section className="panel" aria-labelledby="source-ingestion">
      <h2 id="source-ingestion">Ingestion</h2>
      {!fetched && (
        <p className="muted">
          {`${source.type} sources are not fetched by a worker. Their documents are added directly.`}
        </p>
      )}
      {fetched && can.manage && (
        <>
          <IngestNow sourceId={source.id} onQueued={runs.reload} />
          <Schedule source={source} onSourceChange={onSourceChange} />
        </>
      )}
      <h3>Recent runs</h3>
      <button type="button" className="secondary" onClick={runs.reload} disabled={runs.loading}>
        Refresh runs
      </button>
      {runs.loading && <Loading />}
      <ErrorMessage error={runs.error} />
      {runs.data && <RunTable page={runs.data} />}
    </section>
  );
}

function IngestNow({ sourceId, onQueued }) {
  const { tenantApi } = useOrganization();
  const [state, setState] = useState({ busy: false, error: null, queued: false });

  async function queue() {
    setState({ busy: true, error: null, queued: false });
    try {
      await tenantApi.post("/ingestion-runs", { source_id: sourceId });
      setState({ busy: false, error: null, queued: true });
      onQueued();
    } catch (error) {
      setState({ busy: false, error, queued: false });
    }
  }

  return (
    <div className="form-row">
      <button type="button" disabled={state.busy} onClick={queue}>
        {state.busy ? "Queueing..." : "Ingest now"}
      </button>
      {state.queued && <p role="status">Ingestion was queued. A worker will run it.</p>}
      <ErrorMessage error={state.error} />
    </div>
  );
}

function Schedule({ source, onSourceChange }) {
  const { tenantApi } = useOrganization();
  const [minutes, setMinutes] = useState(String(source.ingestion_interval_minutes ?? 60));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function change(send) {
    setBusy(true);
    setError(null);
    try {
      onSourceChange(await send());
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  function save(event) {
    event.preventDefault();
    change(() =>
      tenantApi.put(`/sources/${source.id}/schedule`, { interval_minutes: Number(minutes) }),
    );
  }

  return (
    <form className="form-row" onSubmit={save} aria-label="Schedule">
      <label>
        Ingest every (minutes)
        <input
          type="number"
          min={1}
          max={MAX_INTERVAL_MINUTES}
          required
          value={minutes}
          onChange={(event) => setMinutes(event.target.value)}
        />
      </label>
      <button type="submit" disabled={busy}>
        {source.ingestion_enabled ? "Update schedule" : "Start schedule"}
      </button>
      {source.ingestion_enabled && (
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() => change(() => tenantApi.delete(`/sources/${source.id}/schedule`))}
        >
          Pause schedule
        </button>
      )}
      <ErrorMessage error={error} />
    </form>
  );
}

function RunTable({ page }) {
  if (page.total === 0) return <p className="muted">This source has no ingestion runs yet.</p>;
  const newestFirst = [...page.items].reverse();
  return (
    <>
      <p className="muted">{`The newest ${page.items.length} of ${page.total} runs.`}</p>
      <table>
        <thead>
          <tr>
            <th scope="col">Status</th>
            <th scope="col">Queued</th>
            <th scope="col">Started</th>
            <th scope="col">Finished</th>
            <th scope="col">Items seen</th>
            <th scope="col">Documents added</th>
            <th scope="col">Duplicates skipped</th>
            <th scope="col">Error</th>
          </tr>
        </thead>
        <tbody>
          {newestFirst.map((run) => (
            <tr key={run.id}>
              <td>{run.status}</td>
              <td>{formatTime(run.created_at)}</td>
              <td>{formatTime(run.started_at)}</td>
              <td>{formatTime(run.finished_at)}</td>
              <td>{run.items_seen}</td>
              <td>{run.documents_created}</td>
              <td>{run.duplicates_skipped}</td>
              <td className="wrap">{run.error_message ?? "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
