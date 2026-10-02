import { useCallback, useState } from "react";
import { Link } from "react-router";

import { useOrganization } from "../../app/useOrganization.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { Pager } from "../../components/Pager.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { formatTime } from "../../lib/format.js";
import { useResource } from "../../lib/useResource.js";
import { SourcePicker } from "../sources/SourcePicker.jsx";
import { useSourceOptions } from "../sources/useSourceOptions.js";

const PAGE_SIZE = 50;
const NO_FILTERS = { source_id: "", language: "", published_from: "", published_to: "" };

/** A date input's day as the start or end of that UTC day. */
function dayBound(day, end) {
  if (!day) return "";
  return `${day}T${end ? "23:59:59.999" : "00:00:00"}Z`;
}

/** Documents of the active organization, with the filters the API supports. */
export function DocumentsPage() {
  const { active, tenantApi, can } = useOrganization();
  const sourceOptions = useSourceOptions();
  const { names } = sourceOptions;
  const [filters, setFilters] = useState(NO_FILTERS);
  const [offset, setOffset] = useState(0);
  const load = useCallback(
    () =>
      tenantApi.get("/documents", {
        query: {
          source_id: filters.source_id,
          language: filters.language,
          published_from: dayBound(filters.published_from, false),
          published_to: dayBound(filters.published_to, true),
          limit: PAGE_SIZE,
          offset,
        },
      }),
    [tenantApi, filters, offset],
  );
  const { data, error, loading } = useResource(load);

  function apply(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setOffset(0);
    setFilters({
      source_id: form.get("source_id"),
      language: form.get("language").trim(),
      published_from: form.get("published_from"),
      published_to: form.get("published_to"),
    });
  }

  return (
    <>
      <PageHeading title="Documents">
        <span className="muted">{active.name}</span>
        {can.contribute && <Link to="/documents/import">Import a file</Link>}
      </PageHeading>
      <section className="panel" aria-labelledby="documents-heading">
        <h2 id="documents-heading">Documents</h2>
        <form className="form-row" role="search" aria-label="Filter documents" onSubmit={apply}>
          <SourcePicker options={sourceOptions} defaultValue={filters.source_id} />
          <label>
            Language
            <input name="language" size={6} defaultValue={filters.language} placeholder="en" />
          </label>
          <label>
            Published from (UTC)
            <input type="date" name="published_from" defaultValue={filters.published_from} />
          </label>
          <label>
            Published to (UTC)
            <input type="date" name="published_to" defaultValue={filters.published_to} />
          </label>
          <button type="submit">Apply</button>
        </form>
        {loading && <Loading />}
        <ErrorMessage error={error} />
        {data && data.items.length > 0 && <DocumentTable documents={data.items} names={names} />}
        {data && (
          <Pager
            offset={offset}
            limit={PAGE_SIZE}
            count={data.items.length}
            total={data.total}
            onChange={setOffset}
            emptyText="No documents match."
          />
        )}
      </section>
    </>
  );
}

function DocumentTable({ documents, names }) {
  return (
    <table>
      <thead>
        <tr>
          <th scope="col">Title</th>
          <th scope="col">Source</th>
          <th scope="col">Published</th>
          <th scope="col">Stored</th>
          <th scope="col">Language</th>
          <th scope="col">URL</th>
        </tr>
      </thead>
      <tbody>
        {documents.map((document) => (
          <tr key={document.id}>
            <td>
              <Link to={`/documents/${document.id}`}>{document.title || "Untitled document"}</Link>
            </td>
            <td>
              <Link to={`/sources/${document.source_id}`}>
                {names.get(document.source_id) ?? "Source"}
              </Link>
            </td>
            <td>{formatTime(document.published_at)}</td>
            <td>{formatTime(document.created_at)}</td>
            <td>{document.language ?? "-"}</td>
            <td className="wrap">{document.url ?? "-"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
