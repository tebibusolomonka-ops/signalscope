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

/** One event, with the chunks that report it in the active organization. */
export function EventDetailPage() {
  const { eventId } = useParams();
  const { tenantApi } = useOrganization();
  const load = useCallback(() => tenantApi.get(`/events/${eventId}`), [tenantApi, eventId]);
  const { data, error, loading } = useResource(load);
  const event = data?.event;

  return (
    <>
      <PageHeading title={event ? event.title : "Event"}>
        <Link to="/events">Timeline</Link>
      </PageHeading>
      {loading && <Loading />}
      <ErrorMessage error={error} />
      {event && (
        <>
          <div className="page-actions">
            <SaveToInvestigation itemType="event" referenceId={event.id} />
          </div>
          <section className="panel" aria-labelledby="event-summary">
            <h2 id="event-summary">Summary</h2>
            <dl className="facts">
              <dt>Event type</dt>
              <dd>{event.event_type}</dd>
              <dt>Occurred</dt>
              <dd>{occurred(event.occurred_at)}</dd>
              <dt>First seen</dt>
              <dd>{formatTime(event.created_at)}</dd>
            </dl>
            {event.summary && <p>{event.summary}</p>}
          </section>
          <section className="panel" aria-labelledby="event-evidence">
            <h2 id="event-evidence">Evidence</h2>
            {data.evidence.length === 0 ? (
              <p className="muted">No evidence in this organization.</p>
            ) : (
              <table aria-label="Evidence">
                <thead>
                  <tr>
                    <th scope="col">Source</th>
                    <th scope="col">Document</th>
                    <th scope="col">Location</th>
                    <th scope="col">Confidence</th>
                    <th scope="col">Found by</th>
                  </tr>
                </thead>
                <tbody>
                  {data.evidence.map((row) => (
                    <tr key={row.chunk_id}>
                      <td>
                        {row.source_id ? (
                          <Link to={`/sources/${row.source_id}`}>
                            {row.source_name ?? "Source"}
                          </Link>
                        ) : (
                          "-"
                        )}
                      </td>
                      <td>
                        <Link to={`/documents/${row.document_id}`}>
                          {row.document_title ?? "Open document"}
                        </Link>
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
