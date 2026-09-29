import { useCallback } from "react";
import { Link, useParams } from "react-router";

import { useOrganization } from "../../app/useOrganization.js";
import { EvidenceTable } from "../../components/EvidenceTable.jsx";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { useResource } from "../../lib/useResource.js";
import { SaveToInvestigation } from "../investigations/SaveToInvestigation.jsx";

/** One entity with its mentions in the active organization's documents. */
export function EntityDetailPage() {
  const { entityId } = useParams();
  const { tenantApi } = useOrganization();
  const load = useCallback(() => tenantApi.get(`/entities/${entityId}`), [tenantApi, entityId]);
  const { data, error, loading } = useResource(load);

  return (
    <>
      <PageHeading title={data ? data.entity.canonical_name : "Entity"}>
        <Link to="/entities">All entities</Link>
      </PageHeading>
      {loading && <Loading />}
      <ErrorMessage error={error} />
      {data && (
        <>
          <div className="page-actions">
            <SaveToInvestigation itemType="entity" referenceId={data.entity.id} />
          </div>
          <section className="panel" aria-labelledby="entity-summary">
            <h2 id="entity-summary">Summary</h2>
            <dl className="facts">
              <dt>Type</dt>
              <dd>{data.entity.entity_type}</dd>
              <dt>Mentions in this organization</dt>
              <dd>{data.mention_count}</dd>
            </dl>
          </section>
          <section className="panel" aria-labelledby="entity-mentions">
            <h2 id="entity-mentions">Mentions</h2>
            {data.mentions.length < data.mention_count && (
              <p className="muted">
                {`The first ${data.mentions.length} of ${data.mention_count} mentions, in document order.`}
              </p>
            )}
            <EvidenceTable rows={data.mentions} label="Mentions" />
          </section>
        </>
      )}
    </>
  );
}
