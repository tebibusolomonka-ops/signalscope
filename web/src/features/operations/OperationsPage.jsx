import { useCallback } from "react";

import { useOrganization } from "../../app/useOrganization.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { formatTime } from "../../lib/format.js";
import { useResource } from "../../lib/useResource.js";
import { queueLabel } from "./queues.js";

/**
 * Job queue counts for the active organization.
 *
 * Owners, admins and system admins see, per queue, how many jobs are pending,
 * running and failed, and how long the oldest pending and failed jobs have
 * waited. Counts are as stored: a running job whose lease ran out still counts
 * as running until a worker puts it back in the queue. There is no live
 * worker status, because the API does not report one.
 */
export function OperationsPage() {
  const { active, tenantApi, can } = useOrganization();
  const load = useCallback(() => tenantApi.get("/operations/overview"), [tenantApi]);
  const { data, error, loading, reload } = useResource(load);

  if (!can.manage) {
    return (
      <>
        <PageHeading title="Operations">
          <span className="muted">{active.name}</span>
        </PageHeading>
        <p className="muted">Operations are for organization owners and admins.</p>
      </>
    );
  }

  return (
    <>
      <PageHeading title="Operations">
        <span className="muted">{active.name}</span>
      </PageHeading>
      <section className="panel" aria-labelledby="queues-heading">
        <div className="form-row">
          <h2 id="queues-heading" className="grow">
            Queues
          </h2>
          <button type="button" className="secondary" onClick={reload} disabled={loading}>
            Refresh
          </button>
        </div>
        <p className="muted">
          Job counts for this organization. States are shown as stored: a running job whose lease
          ran out counts as running until a worker puts it back in the queue.
        </p>
        {loading && <Loading />}
        <ErrorMessage error={error} />
        {data && (
          <table>
            <thead>
              <tr>
                <th scope="col">Queue</th>
                <th scope="col">Pending</th>
                <th scope="col">Running</th>
                <th scope="col">Failed</th>
                <th scope="col">Oldest pending</th>
                <th scope="col">Oldest failed</th>
              </tr>
            </thead>
            <tbody>
              {data.queues.map((queue) => (
                <tr key={queue.queue}>
                  <td>{queueLabel(queue.queue)}</td>
                  <td>{queue.pending_count}</td>
                  <td>{queue.running_count}</td>
                  <td>{queue.failed_count}</td>
                  <td>{formatTime(queue.oldest_pending_at)}</td>
                  <td>{formatTime(queue.oldest_failed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
