import { useCallback } from "react";

import { useAuth } from "../../app/useAuth.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { useResource } from "../../lib/useResource.js";

const DAYS = 14;

function label(key) {
  const text = key.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Counts and daily activity from the dashboard API. No scores or rankings. */
export function DashboardPage() {
  const { api } = useAuth();
  const load = useCallback(async () => {
    const [overview, sources, events] = await Promise.all([
      api.get("/dashboard/overview"),
      api.get("/dashboard/sources", { query: { days: DAYS } }),
      api.get("/dashboard/events", { query: { days: DAYS } }),
    ]);
    return { overview, sources, events };
  }, [api]);
  const { data, error, loading } = useResource(load);

  return (
    <>
      <PageHeading title="Dashboard" />
      {loading && <Loading />}
      <ErrorMessage error={error} />
      {data && (
        <>
          <section className="panel" aria-labelledby="overview-heading">
            <h2 id="overview-heading">Records and open jobs</h2>
            <dl className="cards">
              {Object.entries(data.overview).map(([key, value]) => (
                <div className="card" key={key}>
                  <dt>{label(key)}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          </section>
          <ActivityTable
            title={`Documents per day (last ${DAYS} days, UTC)`}
            items={data.sources.items}
            columns={["documents_created", "documents_published"]}
          />
          <ActivityTable
            title={`Events per day (last ${DAYS} days, UTC)`}
            items={data.events.items}
            columns={["events", "clusters", "cross_source_clusters"]}
          />
        </>
      )}
    </>
  );
}

function ActivityTable({ title, items, columns }) {
  const largest = Math.max(1, ...items.map((item) => item[columns[0]]));
  return (
    <section className="panel" aria-label={title}>
      <h2>{title}</h2>
      <table>
        <thead>
          <tr>
            <th scope="col">Date</th>
            {columns.map((column) => (
              <th scope="col" key={column}>
                {label(column)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.date}>
              <th scope="row">{item.date}</th>
              {columns.map((column, index) => (
                <td key={column}>
                  {item[column]}
                  {index === 0 && (
                    <svg className="bar" width="100" height="8" aria-hidden="true">
                      <rect width={(100 * item[column]) / largest} height="8" />
                    </svg>
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
