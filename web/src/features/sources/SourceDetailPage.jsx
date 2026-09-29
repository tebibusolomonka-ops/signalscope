import { Fragment, useCallback, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { useOrganization } from "../../app/useOrganization.js";
import { ConfirmAction } from "../../components/ConfirmAction.jsx";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { formatTime } from "../../lib/format.js";
import { useResource } from "../../lib/useResource.js";
import { SaveToInvestigation } from "../investigations/SaveToInvestigation.jsx";
import { SourceOperations } from "./SourceOperations.jsx";
import { scheduleText } from "./sourceText.js";

/** One source: its configuration and what SignalScope has observed from it. */
export function SourceDetailPage() {
  const { sourceId } = useParams();
  const { tenantApi, can } = useOrganization();
  const navigate = useNavigate();
  const load = useCallback(() => tenantApi.get(`/sources/${sourceId}`), [tenantApi, sourceId]);
  const { data, error, loading } = useResource(load);
  // A schedule change answers with the changed source.
  const [changed, setChanged] = useState(null);
  const source = changed ?? data;

  async function remove() {
    await tenantApi.delete(`/sources/${sourceId}`);
    navigate("/sources");
  }

  return (
    <>
      <PageHeading title={source ? source.name : "Source"}>
        <Link to="/sources">All sources</Link>
      </PageHeading>
      {loading && <Loading />}
      <ErrorMessage error={error} />
      {source && (
        <>
          <div className="page-actions">
            <SaveToInvestigation itemType="source" referenceId={source.id} />
          </div>
          <section className="panel" aria-labelledby="source-configuration">
            <h2 id="source-configuration">Configuration</h2>
            <dl className="facts">
              <dt>Type</dt>
              <dd>{source.type}</dd>
              <dt>URL</dt>
              <dd>{source.url ?? "-"}</dd>
              <dt>Scheduled ingestion</dt>
              <dd>{scheduleText(source)}</dd>
              <dt>Next ingestion</dt>
              <dd>{source.ingestion_enabled ? formatTime(source.next_ingestion_at) : "-"}</dd>
              <dt>Created</dt>
              <dd>{formatTime(source.created_at)}</dd>
              <dt>Updated</dt>
              <dd>{formatTime(source.updated_at)}</dd>
            </dl>
          </section>
          <SourceOperations source={source} onSourceChange={setChanged} />
          <Provenance sourceId={source.id} />
          {can.manage && (
            <section className="panel" aria-labelledby="source-delete">
              <h2 id="source-delete">Delete</h2>
              <p className="muted">
                Deleting a source also deletes its documents and everything extracted from them.
              </p>
              <ConfirmAction
                label="Delete source"
                question={`Delete "${source.name}" and all of its documents? This cannot be undone.`}
                confirmLabel="Yes, delete source"
                onConfirm={remove}
              />
            </section>
          )}
        </>
      )}
    </>
  );
}

const PROVENANCE = [
  ["document_count", "Documents"],
  ["first_document_at", "First document stored", formatTime],
  ["last_document_at", "Last document stored", formatTime],
  ["first_published_at", "First published", formatTime],
  ["last_published_at", "Last published", formatTime],
  ["revision_count", "Document revisions"],
  ["entity_count", "Entities"],
  ["claim_count", "Claims"],
  ["event_count", "Events"],
  ["event_cluster_count", "Event clusters"],
  ["cross_source_event_cluster_count", "Event clusters also reported by other sources"],
];

function Provenance({ sourceId }) {
  const { tenantApi } = useOrganization();
  const load = useCallback(
    () => tenantApi.get(`/sources/${sourceId}/provenance`),
    [tenantApi, sourceId],
  );
  const { data, error, loading } = useResource(load);
  return (
    <section className="panel" aria-labelledby="source-provenance">
      <h2 id="source-provenance">Provenance</h2>
      <p className="muted">
        Observed counts and dates in this organization. They describe the source; they are not a
        score.
      </p>
      {loading && <Loading />}
      <ErrorMessage error={error} />
      {data && (
        <dl className="facts">
          {PROVENANCE.map(([key, label, format]) => (
            <Fragment key={key}>
              <dt>{label}</dt>
              <dd>{format ? format(data[key]) : data[key]}</dd>
            </Fragment>
          ))}
        </dl>
      )}
    </section>
  );
}
