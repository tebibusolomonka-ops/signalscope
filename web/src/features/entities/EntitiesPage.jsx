import { useCallback, useState } from "react";
import { Link } from "react-router";

import { useOrganization } from "../../app/useOrganization.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { Pager } from "../../components/Pager.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { useResource } from "../../lib/useResource.js";

const PAGE_SIZE = 50;

/**
 * Entities mentioned in the active organization's documents.
 *
 * Entity names are shared rows; the counts cover this organization only.
 */
export function EntitiesPage() {
  const { active, tenantApi } = useOrganization();
  const [filters, setFilters] = useState({ query: "", entity_type: "" });
  const [offset, setOffset] = useState(0);
  const load = useCallback(
    () => tenantApi.get("/entities", { query: { ...filters, limit: PAGE_SIZE, offset } }),
    [tenantApi, filters, offset],
  );
  const { data, error, loading } = useResource(load);

  function apply(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setOffset(0);
    setFilters({ query: form.get("query").trim(), entity_type: form.get("entity_type").trim() });
  }

  return (
    <>
      <PageHeading title="Entities">
        <span className="muted">{active.name}</span>
      </PageHeading>
      <section className="panel" aria-labelledby="entities-heading">
        <h2 id="entities-heading">Entities</h2>
        <p className="muted">
          People, places, organizations and other names found in this organization&apos;s documents.
          Mention counts cover this organization only.
        </p>
        <form className="form-row" role="search" aria-label="Filter entities" onSubmit={apply}>
          <label>
            Name contains
            <input name="query" defaultValue={filters.query} />
          </label>
          <label>
            Type
            <input name="entity_type" defaultValue={filters.entity_type} placeholder="person" />
          </label>
          <button type="submit">Apply</button>
        </form>
        {loading && <Loading />}
        <ErrorMessage error={error} />
        {data && data.items.length > 0 && (
          <table>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Type</th>
                <th scope="col">Mentions here</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((entity) => (
                <tr key={entity.id}>
                  <td>
                    <Link to={`/entities/${entity.id}`}>{entity.canonical_name}</Link>
                  </td>
                  <td>{entity.entity_type}</td>
                  <td>{entity.mention_count}</td>
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
            emptyText="No entities match."
          />
        )}
      </section>
    </>
  );
}
