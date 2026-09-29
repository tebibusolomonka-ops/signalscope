import { useCallback } from "react";
import { Link, useParams } from "react-router";

import { useOrganization } from "../../app/useOrganization.js";
import { EvidenceTable } from "../../components/EvidenceTable.jsx";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { useResource } from "../../lib/useResource.js";

/** One claim with its evidence in the active organization's documents. */
export function ClaimDetailPage() {
  const { claimId } = useParams();
  const { tenantApi } = useOrganization();
  const load = useCallback(() => tenantApi.get(`/claims/${claimId}`), [tenantApi, claimId]);
  const { data, error, loading } = useResource(load);

  return (
    <>
      <PageHeading title="Claim">
        <Link to="/claims">All claims</Link>
      </PageHeading>
      {loading && <Loading />}
      <ErrorMessage error={error} />
      {data && (
        <>
          <section className="panel" aria-labelledby="claim-summary">
            <h2 id="claim-summary">Statement</h2>
            <blockquote className="claim-text">{data.claim.text}</blockquote>
            <dl className="facts">
              <dt>Type</dt>
              <dd>{data.claim.claim_type}</dd>
              <dt>Evidence in this organization</dt>
              <dd>{data.evidence_count}</dd>
            </dl>
            <p className="muted">
              An extracted statement and where documents make it. It has not been checked.
            </p>
          </section>
          <section className="panel" aria-labelledby="claim-evidence">
            <h2 id="claim-evidence">Evidence</h2>
            {data.evidence.length < data.evidence_count && (
              <p className="muted">
                {`The first ${data.evidence.length} of ${data.evidence_count} evidence rows, in document order.`}
              </p>
            )}
            <EvidenceTable rows={data.evidence} label="Evidence" />
          </section>
        </>
      )}
    </>
  );
}
