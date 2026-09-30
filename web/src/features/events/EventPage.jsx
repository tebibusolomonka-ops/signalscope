import { useCallback } from "react";
import { Link, useParams } from "react-router";

import { useOrganization } from "../../app/useOrganization.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { chunkLocation } from "../../lib/chunks.js";
import { formatTime } from "../../lib/format.js";
import { useResource } from "../../lib/useResource.js";
import { SaveToInvestigation } from "../investigations/SaveToInvestigation.jsx";

function occurred(value) {
  return value ? formatTime(value) : "Date unknown";
}

/**
 * One event: its fields and the chunks that report it.
 *
 * Reached from the timeline and from a cluster's member events. Read only.
 * Each evidence row links to the document it was found in.
 */
export function EventPage() {
  const { eventId } = useParams();
  const { tenantApi } = useOrganization();
  const load = useCallback(() => tenantApi.get(`/events/${eventId}`), [tenantApi, eventId]);
  const { data, error, loading } = useResource(load);

  return (
    <>
      <PageHeading title={data ? data.event.title : "Event"}>
        <Link to="/events">Timeline</Link>
      </PageHeading>
      {loading && <Loading />}
      <ErrorMessage error={error} />
      {data && (
        <>
          <div className="page-actions">
            <SaveToInvestigation itemType="event" referenceId={data.event.id} />
          </div>
          <section className="panel" aria-labelledby="event-summary">
            <h2 id="event-summary">Summary</h2>
            <dl className="facts">
              <dt>Event type</dt>
              <dd>{data.event.event_type}</dd>
              <dt>Occurred</dt>
              <dd>{occurred(data.event.occurred_at)}</dd>
              <dt>First seen</dt>
              <dd>{formatTime(data.event.created_at)}</dd>
            </dl>
            {data.event.summary && <p>{data.event.summary}</p>}
          </section>
          <section className="panel" aria-labelledby="event-evidence">
            <h2 id="event-evidence">Evidence</h2>
            <p className="muted">Where this event is reported, in document order.</p>
            {data.evidence.length === 0 ? (
              <p className="muted">No evidence in this organization.</p>
            ) : (
              <table aria-label="Event evidence">
                <thead>
                  <tr>
                    <th scope="col">Document</th>
                    <th scope="col">Source</th>
                    <th scope="col">Location</th>
                    <th scope="col">Confidence</th>
                    <th scope="col">Found by</th>
                  </tr>
                </thead>
                <tbody>
                  {data.evidence.map((row) => (
                    <tr key={row.chunk_id}>
                      <td className="wrap">
                        <Link to={`/documents/${row.document_id}`}>
                          {row.document_title || "Untitled document"}
                        </Link>
                      </td>
                      <td>
                        <Link to={`/sources/${row.source_id}`}>{row.source_name}</Link>
                      </td>
                      <td>{chunkLocation(row.chunk_metadata) || "-"}</td>
                      <td>{row.confidence === null ? "-" : Number(row.confidence).toFixed(2)}</td>
                      <td className="wrap">{`${row.provider} / ${row.model}`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </>
  );
}
