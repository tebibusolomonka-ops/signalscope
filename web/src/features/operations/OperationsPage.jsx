import { useCallback } from "react";

import { useOrganization } from "../../app/useOrganization.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { formatTime } from "../../lib/format.js";
import { useResource } from "../../lib/useResource.js";
import { QUEUE_LABELS } from "./queues.js";

/**
 * Job counts per queue for the active organization.
 *
 * Only owners, admins and system admins can use the API behind it; a member
 * or viewer gets a clear message and no request is made. Running counts
 * include jobs whose lease ran out, as the backend stores them.
 */
export function OperationsPage() {
  const { active, can } = useOrganization();
  return (
    <>
      <PageHeading title="Operations">
        <span className="muted">{active.name}</span>
      </PageHeading>
      {can.manage ? (
        <Queues />
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
