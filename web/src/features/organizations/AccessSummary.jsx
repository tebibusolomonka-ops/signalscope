import { useCallback } from "react";

import { useAuth } from "../../app/useAuth.js";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { useResource } from "../../lib/useResource.js";

const GROUPS = [
  ["members", "Members"],
  ["member_status", "Member status"],
  ["invitations", "Invitations"],
  ["investigations", "Investigations"],
  ["collaborators", "Investigation collaborators"],
];

/** Counts from the API only; no scores. Members without access see the API's answer. */
export function AccessSummary({ organizationId }) {
  const { api } = useAuth();
  const load = useCallback(
    () => api.get(`/organizations/${organizationId}/access-summary`),
    [api, organizationId],
  );
  const { data, error, loading } = useResource(load);

  return (
    <section className="panel" aria-labelledby="summary-heading">
      <h2 id="summary-heading">Access summary</h2>
      {loading && <Loading />}
      <ErrorMessage error={error} />
      {data &&
        GROUPS.map(([key, label]) => (
          <div key={key}>
            <h3>{label}</h3>
            <dl className="cards">
              {Object.entries(data[key]).map(([name, count]) => (
                <div className="card" key={name}>
                  <dt>{name}</dt>
                  <dd>{count}</dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
    </section>
  );
}
