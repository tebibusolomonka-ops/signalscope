import { useCallback, useState } from "react";
import { Link } from "react-router";

import { useOrganization } from "../../app/useOrganization.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { Pager } from "../../components/Pager.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { useResource } from "../../lib/useResource.js";

const PAGE_SIZE = 50;

/**
 * Claims found in the active organization's documents.
 *
 * A claim is a statement a document makes, with the places it was found.
 * SignalScope does not judge whether it is true.
 */
export function ClaimsPage() {
  const { active, tenantApi } = useOrganization();
  const [filters, setFilters] = useState({ query: "", claim_type: "" });
  const [offset, setOffset] = useState(0);
  const load = useCallback(
    () => tenantApi.get("/claims", { query: { ...filters, limit: PAGE_SIZE, offset } }),
    [tenantApi, filters, offset],
  );
  const { data, error, loading } = useResource(load);

  function apply(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setOffset(0);
    setFilters({ query: form.get("query").trim(), claim_type: form.get("claim_type").trim() });
  }

  return (
    <>
      <PageHeading title="Claims">
        <span className="muted">{active.name}</span>
      </PageHeading>
      <section className="panel" aria-labelledby="claims-heading">
        <h2 id="claims-heading">Claims</h2>
        <p className="muted">
          Statements extracted from this organization&apos;s documents, with where they were found.
          They are not checked for truth. Evidence counts cover this organization only.
        </p>
        <form className="form-row" role="search" aria-label="Filter claims" onSubmit={apply}>
          <label className="grow">
            Text contains
            <input name="query" defaultValue={filters.query} />
          </label>
          <label>
            Type
            <input name="claim_type" defaultValue={filters.claim_type} placeholder="statistic" />
          </label>
          <button type="submit">Apply</button>
        </form>
        {loading && <Loading />}
        <ErrorMessage error={error} />
        {data && data.items.length > 0 && (
          <table>
            <thead>
              <tr>
                <th scope="col">Claim</th>
                <th scope="col">Type</th>
                <th scope="col">Evidence here</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((claim) => (
                <tr key={claim.id}>
                  <td className="wrap">
                    <Link to={`/claims/${claim.id}`}>{claim.text}</Link>
                  </td>
                  <td>{claim.claim_type}</td>
                  <td>{claim.evidence_count}</td>
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
            emptyText="No claims match."
          />
        )}
      </section>
    </>
  );
}
