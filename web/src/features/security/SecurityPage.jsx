import { useCallback, useState } from "react";

import { useAuth } from "../../app/useAuth.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { useResource } from "../../lib/useResource.js";
import { MySessions } from "./MySessions.jsx";

const PAGE_SIZE = 20;
const MANAGER_ROLES = ["owner", "admin"];

function nextDay(date) {
  const day = new Date(`${date}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate() + 1);
  return day.toISOString();
}

/** Builds the audit query. Dates are whole UTC days; the end day is included. */
function auditQuery(filters, offset) {
  return {
    organization_id: filters.organization_id,
    action: filters.action,
    resource_type: filters.resource_type,
    created_from: filters.from ? `${filters.from}T00:00:00Z` : undefined,
    created_to: filters.to ? nextDay(filters.to) : undefined,
    limit: PAGE_SIZE,
    offset,
  };
}

export function SecurityPage() {
  const { api, user } = useAuth();
  const loadOrganizations = useCallback(() => api.get("/organizations"), [api]);
  const organizations = useResource(loadOrganizations);
  const managed = (organizations.data ?? [])
    .filter((item) => MANAGER_ROLES.includes(item.role))
    .map((item) => item.organization);

  return (
    <>
      <PageHeading title="Security" />
      {organizations.loading && <Loading />}
      {!organizations.loading &&
        (user.is_system_admin || managed.length > 0 ? (
          <AuditLog organizations={managed} allowAll={user.is_system_admin} />
        ) : (
          <p className="muted">
            The audit log is for system admins and organization owners and admins.
          </p>
        ))}
      <MySessions />
    </>
  );
}

function AuditLog({ organizations, allowAll }) {
  const { api } = useAuth();
  const [filters, setFilters] = useState({
    organization_id: allowAll ? "" : organizations[0].id,
    action: "",
    resource_type: "",
    from: "",
    to: "",
  });
  const [offset, setOffset] = useState(0);
  const load = useCallback(
    () => api.get("/security/audit", { query: auditQuery(filters, offset) }),
    [api, filters, offset],
  );
  const { data, error, loading } = useResource(load);

  function apply(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setOffset(0);
    setFilters({
      organization_id: form.get("organization_id"),
      action: form.get("action").trim(),
      resource_type: form.get("resource_type").trim(),
      from: form.get("from"),
      to: form.get("to"),
    });
  }

  return (
    <section className="panel" aria-labelledby="audit-heading">
      <h2 id="audit-heading">Audit log</h2>
      <form className="form-row" onSubmit={apply}>
        <label>
          Organization
          <select name="organization_id" defaultValue={filters.organization_id}>
            {allowAll && <option value="">All organizations</option>}
            {organizations.map((organization) => (
              <option key={organization.id} value={organization.id}>
                {organization.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Action
          <input name="action" defaultValue={filters.action} placeholder="auth.login" />
        </label>
        <label>
          Resource type
          <input name="resource_type" defaultValue={filters.resource_type} />
        </label>
        <label>
          From (UTC)
          <input name="from" type="date" defaultValue={filters.from} />
        </label>
        <label>
          To (UTC)
          <input name="to" type="date" defaultValue={filters.to} />
        </label>
        <button type="submit">Search audit log</button>
      </form>
      {loading && <Loading />}
      <ErrorMessage error={error} />
      {data && (
        <>
          <table>
            <thead>
              <tr>
                <th scope="col">Time (UTC)</th>
                <th scope="col">Action</th>
                <th scope="col">Actor</th>
                <th scope="col">Resource</th>
                <th scope="col">Details</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((event) => (
                <tr key={event.id}>
                  <td>{event.created_at}</td>
                  <td>{event.action}</td>
                  <td>{event.actor ? event.actor.email : "None"}</td>
                  <td>
                    {event.resource_type}
                    {event.resource_id && <span className="muted"> {event.resource_id}</span>}
                  </td>
                  <td>
                    {Object.entries(event.metadata)
                      .map(([key, value]) => `${key}: ${value}`)
                      .join(", ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">{data.total} events</p>
          <div className="form-row">
            <button
              type="button"
              className="secondary"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Newer events
            </button>
            <button
              type="button"
              className="secondary"
              disabled={offset + PAGE_SIZE >= data.total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Older events
            </button>
          </div>
        </>
      )}
    </section>
  );
}
