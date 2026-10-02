import { useCallback, useState } from "react";

import { useOrganization } from "../../app/useOrganization.js";
import { ConfirmAction } from "../../components/ConfirmAction.jsx";
import { PageHeading } from "../../components/PageHeading.jsx";
import { Pager } from "../../components/Pager.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { formatTime } from "../../lib/format.js";
import { useResource } from "../../lib/useResource.js";
import { QUEUE_LABELS } from "./queues.js";

const PAGE_SIZE = 20;

/**
 * Queue counts and failed jobs for the active organization, with retry.
 *
 * Only owners, admins and system admins can use the API behind it; a member
 * or viewer gets a clear message and no request is made.
 */
export function OperationsPage() {
  const { active, can } = useOrganization();
  // Bumped after a retry, so the Queues panel remounts and reloads its counts.
  const [overviewKey, setOverviewKey] = useState(0);
  const refreshOverview = useCallback(() => setOverviewKey((value) => value + 1), []);

  return (
    <>
      <PageHeading title="Operations">
        <span className="muted">{active.name}</span>
      </PageHeading>
      {can.manage ? (
        <>
          <Queues key={overviewKey} />
          <FailedJobs onRetried={refreshOverview} />
        </>
      ) : (
        <p className="muted">Only organization owners and admins can see operations.</p>
      )}
    </>
  );
}

function Queues() {
  const { tenantApi } = useOrganization();
  const load = useCallback(() => tenantApi.get("/operations/overview"), [tenantApi]);
  const { data, error, loading, reload } = useResource(load);

  return (
    <section className="panel" aria-labelledby="queues-heading">
      <div className="form-row">
        <h2 id="queues-heading">Queues</h2>
        <button type="button" className="secondary" onClick={reload} disabled={loading}>
          Refresh
        </button>
      </div>
      <p className="muted">
        Jobs waiting, running and failed in this organization. A running job whose lease ran out
        still counts as running until a worker takes it back.
      </p>
      {loading && <Loading />}
      <ErrorMessage error={error} />
      {data && <QueueTable queues={data.queues} />}
    </section>
  );
}

function QueueTable({ queues }) {
  return (
    <table>
      <thead>
        <tr>
          <th scope="col">Queue</th>
          <th scope="col">Pending</th>
          <th scope="col">Running</th>
          <th scope="col">Failed</th>
          <th scope="col">Oldest pending</th>
          <th scope="col">Oldest failure</th>
        </tr>
      </thead>
      <tbody>
        {queues.map((queue) => (
          <tr key={queue.queue}>
            <th scope="row">{QUEUE_LABELS[queue.queue] ?? queue.queue}</th>
            <td>{queue.pending_count}</td>
            <td>{queue.running_count}</td>
            <td>{queue.failed_count}</td>
            <td>{queue.oldest_pending_at ? formatTime(queue.oldest_pending_at) : "-"}</td>
            <td>{queue.oldest_failed_at ? formatTime(queue.oldest_failed_at) : "-"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function FailedJobs({ onRetried }) {
  const { tenantApi } = useOrganization();
  const [queue, setQueue] = useState("");
  const [offset, setOffset] = useState(0);
  const load = useCallback(
    () =>
      tenantApi.get("/operations/jobs", {
        query: { status: "failed", queue, limit: PAGE_SIZE, offset },
      }),
    [tenantApi, queue, offset],
  );
  const { data, error, loading, reload } = useResource(load);

  async function retry(job) {
    await tenantApi.post(`/operations/jobs/${job.queue}/${job.job_id}/retry`, {
      organization_id: tenantApi.organizationId,
    });
    reload();
    onRetried();
  }

  return (
    <section className="panel" aria-labelledby="failed-heading">
      <h2 id="failed-heading">Failed jobs</h2>
      <label className="inline">
        Queue
        <select
          value={queue}
          onChange={(event) => {
            setOffset(0);
            setQueue(event.target.value);
          }}
        >
          <option value="">All queues</option>
          {Object.entries(QUEUE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {loading && <Loading />}
      <ErrorMessage error={error} />
      {data && data.items.length > 0 && (
        <table>
          <thead>
            <tr>
              <th scope="col">Queue</th>
              <th scope="col">Works on</th>
              <th scope="col">Attempts</th>
              <th scope="col">Failed at</th>
              <th scope="col">Error</th>
              <th scope="col">Retry</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((job) => (
              <tr key={job.job_id}>
                <td>{QUEUE_LABELS[job.queue] ?? job.queue}</td>
                <td>{`${job.resource_type} ${job.resource_id}`}</td>
                <td>{job.attempt_count}</td>
                <td>{job.finished_at ? formatTime(job.finished_at) : "-"}</td>
                <td className="wrap">{job.error ?? "-"}</td>
                <td>
                  <ConfirmAction
                    label="Retry"
                    question="Put this job back in its queue to run again?"
                    confirmLabel="Yes, retry"
                    onConfirm={() => retry(job)}
                  />
                </td>
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
          emptyText="No failed jobs."
        />
      )}
    </section>
  );
}
