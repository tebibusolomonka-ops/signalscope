import { useCallback, useState } from "react";
import { Link, useParams } from "react-router";

import { useOrganization } from "../../app/useOrganization.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { EvidenceReference } from "../../components/EvidenceReference.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { formatTime } from "../../lib/format.js";
import { useResource } from "../../lib/useResource.js";
import { SaveToInvestigation } from "../investigations/SaveToInvestigation.jsx";

function occurred(value) {
  return value ? formatTime(value) : "Date unknown";
}

/**
 * One event cluster: the events that report the same thing and where each
 * was reported. Read only; clusters are never merged or split here.
 */
export function EventClusterPage() {
  const { clusterId } = useParams();
  const { tenantApi } = useOrganization();
  const load = useCallback(
    () => tenantApi.get(`/event-clusters/${clusterId}`),
    [tenantApi, clusterId],
  );
  const { data, error, loading } = useResource(load);

  return (
    <>
      <PageHeading title={data ? data.title : "Event cluster"}>
        <Link to="/events">Timeline</Link>
      </PageHeading>
      {loading && <Loading />}
      <ErrorMessage error={error} />
      {data && (
        <>
          <div className="page-actions">
            <SaveToInvestigation itemType="event_cluster" referenceId={data.cluster_id} />
          </div>
          <section className="panel" aria-labelledby="cluster-summary">
            <h2 id="cluster-summary">Summary</h2>
            <dl className="facts">
              <dt>Event type</dt>
              <dd>{data.event_type}</dd>
              <dt>Occurred</dt>
              <dd>{occurred(data.occurred_at)}</dd>
              <dt>Events</dt>
              <dd>{data.event_count}</dd>
              <dt>Sources</dt>
              <dd>{data.source_count}</dd>
              <dt>Evidence rows</dt>
              <dd>{data.evidence_count}</dd>
            </dl>
          </section>
          <section className="panel" aria-labelledby="cluster-members">
            <h2 id="cluster-members">Member events</h2>
            {data.members.map((member) => (
              <Member key={member.event_id} member={member} clusterId={data.cluster_id} />
            ))}
          </section>
        </>
      )}
    </>
  );
}

function Member({ member, clusterId }) {
  const [showSuggestions, setShowSuggestions] = useState(false);
  return (
    <article className="member" aria-labelledby={`event-${member.event_id}`}>
      <h3 id={`event-${member.event_id}`}>
        <Link to={`/events/${member.event_id}`}>{member.title}</Link>
      </h3>
      <p className="muted">{`Occurred: ${occurred(member.occurred_at)}`}</p>
      {member.summary && <p>{member.summary}</p>}
      <table aria-label={`Evidence for ${member.title}`}>
        <thead>
          <tr>
            <th scope="col">Where</th>
            <th scope="col">Confidence</th>
            <th scope="col">Found by</th>
          </tr>
        </thead>
        <tbody>
          {member.evidence.map((row) => (
            <tr key={row.chunk_id}>
              <td>
                <EvidenceReference
                  documentId={row.document_id}
                  sourceId={row.source_id}
                  sourceName={row.source_name}
                  metadata={row.chunk_metadata}
                />
              </td>
              <td>{row.confidence === null ? "-" : Number(row.confidence).toFixed(2)}</td>
              <td className="wrap">{`${row.provider} / ${row.model}`}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="page-actions">
        <SaveToInvestigation itemType="event" referenceId={member.event_id} />
      </div>
      {showSuggestions ? (
        <Suggestions eventId={member.event_id} clusterId={clusterId} />
      ) : (
        <button type="button" className="secondary" onClick={() => setShowSuggestions(true)}>
          Show suggested similar events
        </button>
      )}
    </article>
  );
}

function Suggestions({ eventId, clusterId }) {
  const { tenantApi } = useOrganization();
  const load = useCallback(
    () => tenantApi.get(`/events/${eventId}/link-suggestions`),
    [tenantApi, eventId],
  );
  const { data, error, loading } = useResource(load);
  return (
    <section aria-label="Suggested similar events" className="suggestions">
      <h4>Suggested similar events</h4>
      <p className="muted">
        Events whose text is close to this one by meaning. They are suggestions only and are not
        linked to this cluster.
      </p>
      {loading && <Loading />}
      {error?.status === 503 ? (
        <p className="error" role="alert">
          {`Suggestions are not available: ${error.message}`}
        </p>
      ) : (
        <ErrorMessage error={error} />
      )}
      {data && data.length === 0 && <p className="muted">No similar events found.</p>}
      {data && data.length > 0 && (
        <table>
          <thead>
            <tr>
              <th scope="col">Event</th>
              <th scope="col">Occurred</th>
              <th scope="col">Cosine similarity</th>
              <th scope="col">Its cluster</th>
            </tr>
          </thead>
          <tbody>
            {data.map((item) => (
              <tr key={item.candidate_event_id}>
                <td className="wrap">{item.title}</td>
                <td>{occurred(item.occurred_at)}</td>
                <td>{Number(item.similarity).toFixed(3)}</td>
                <td>
                  {!item.candidate_cluster_id && "None"}
                  {item.candidate_cluster_id === clusterId && "This cluster"}
                  {item.candidate_cluster_id && item.candidate_cluster_id !== clusterId && (
                    <Link to={`/event-clusters/${item.candidate_cluster_id}`}>Open cluster</Link>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
