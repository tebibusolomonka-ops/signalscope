import { useCallback, useState } from "react";

import { useOrganization } from "../../app/useOrganization.js";
import { ConfirmAction } from "../../components/ConfirmAction.jsx";
import { PageHeading } from "../../components/PageHeading.jsx";
import { Pager } from "../../components/Pager.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { formatTime } from "../../lib/format.js";
import { useResource } from "../../lib/useResource.js";
import { QUEUE_LABELS, queueLabel } from "./queues.js";

const PAGE_SIZE = 20;

/**
 * Failed jobs of the active organization, with a retry.
 *
 * Owners, admins and system admins list failed jobs, newest failure first,
 * from one queue or all, and put one back in its queue after confirming.
 * Only the short stored error is shown, never a traceback. After a retry the
 * list is loaded again, so the job that is no longer failed drops out.
 */
export function FailedJobsPage() {
  const { active, tenantApi, can } = useOrganization();
  const [queue, setQueue] = useState("");
  const [offset, setOffset] = useState(0);
  const load = useCallback(
    () =>
      tenantApi.get("/operations/jobs", {
        query: { queue: queue || undefined, limit: PAGE_SIZE, offset },
      }),
    [tenantApi, queue, offset],
  );
  const { data, error, loading, reload } = useResource(load);

  if (!can.manage) {
    return (
      <>
        <PageHeading title="Failed jobs">
          <span className="muted">{active.name}</span>
        </PageHeading>
        <p className="muted">Failed jobs are for organization owners and admins.</p>
      </>
    );
  }

  async function retry(job) {
    await tenantApi.post("/operations/jobs/retry", { queue: job.queue, job_id: job.job_id });
    reload();
  }

  function changeQueue(event) {
    setOffset(0);
    setQueue(event.target.value);
  }

  return (
    <>
      <PageHeading title="Failed jobs">
        <span className="muted">{active.name}</span>
      </PageHeading>
      <section className="panel" aria-labelledby="failed-heading">
        <div className="form-row">
          <h2 id="failed-heading" className="grow">
            Failed jobs
          </h2>
          <label>
            Queue
            <select value={queue} onChange={changeQueue}>
              <option value="">All queues</option>
              {Object.entries(QUEUE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="secondary" onClick={reload} disabled={loading}>
            Refresh
          </button>
        </div>
        <p className="muted">
          Jobs that failed, newest first. Retrying puts a job back in its queue for a worker to run
          again. The message is the short reason stored when the job failed.
        </p>
        {loading && <Loading />}
        <ErrorMessage error={error} />
        {data && data.items.length > 0 && (
          <table>
            <thead>
              <tr>
                <th scope="col">Queue</th>
                <th scope="col">Works on</th>
                <th scope="col">Model</th>
                <th scope="col">Attempts</th>
                <th scope="col">Failed</th>
                <th scope="col">Error</th>
                <th scope="col">Retry</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((job) => (
                <tr key={job.job_id}>
                  <td>{queueLabel(job.queue)}</td>
                  <td>
                    {job.resource_type}
                    <span className="muted"> {job.resource_id}</span>
                  </td>
                  <td>{job.model ? `${job.provider}/${job.model}` : "-"}</td>
                  <td>{job.attempt_count}</td>
                  <td>{formatTime(job.finished_at)}</td>
                  <td className="wrap">{job.error ?? "-"}</td>
                  <td>
                    <ConfirmAction
                      label="Retry"
                      question={`Retry this ${queueLabel(job.queue).toLowerCase()} job?`}
                      confirmLabel="Retry job"
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
    </>
  );
}
