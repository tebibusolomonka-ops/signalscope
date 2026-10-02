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
const NO_FILTERS = {
  event_type: "",
  occurred_from: "",
  occurred_to: "",
  source_id: "",
  order: "newest_first",
};

function dayStart(day) {
  return day ? `${day}T00:00:00Z` : "";
}

/** The start of the day after, so the whole "to" day is included. */
function dayAfter(day) {
  if (!day) return "";
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().replace(".000Z", "Z");
}

/**
 * Event clusters of the active organization in time order.
 *
 * Rows are in the API's time order; the timeline does not rank events.
 */
export function TimelinePage() {
  const { active, tenantApi } = useOrganization();
  const sourceOptions = useSourceOptions();
  const [filters, setFilters] = useState(NO_FILTERS);
  const [offset, setOffset] = useState(0);
  const load = useCallback(
    () =>
      tenantApi.get("/timeline", {
        query: {
          event_type: filters.event_type,
          occurred_from: dayStart(filters.occurred_from),
          occurred_to: dayAfter(filters.occurred_to),
          source_id: filters.source_id,
          order: filters.order,
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
      event_type: form.get("event_type").trim(),
      occurred_from: form.get("occurred_from"),
      occurred_to: form.get("occurred_to"),
      source_id: form.get("source_id"),
      order: form.get("order"),
    });
  }

  return (
    <>
      <PageHeading title="Events">
        <span className="muted">{active.name}</span>
      </PageHeading>
      <section className="panel" aria-labelledby="timeline-heading">
        <h2 id="timeline-heading">Timeline</h2>
        <p className="muted">
          Each row is a cluster of events that report the same thing, in time order. Counts cover
          this organization&apos;s documents. Events without a known date come last, and are left
          out when a date filter is set.
        </p>
        <form className="form-row" role="search" aria-label="Filter events" onSubmit={apply}>
          <label>
            Event type
            <input name="event_type" defaultValue={filters.event_type} placeholder="flood" />
          </label>
          <label>
            From (UTC)
            <input type="date" name="occurred_from" defaultValue={filters.occurred_from} />
          </label>
          <label>
            To (UTC)
            <input type="date" name="occurred_to" defaultValue={filters.occurred_to} />
          </label>
          <SourcePicker options={sourceOptions} defaultValue={filters.source_id} />
          <label>
            Order
            <select name="order" defaultValue={filters.order}>
              <option value="newest_first">Newest first</option>
              <option value="oldest_first">Oldest first</option>
            </select>
          </label>
          <button type="submit">Apply</button>
        </form>
        {loading && <Loading />}
        <ErrorMessage error={error} />
        {data && data.items.length > 0 && <TimelineTable items={data.items} />}
        {data && (
          <Pager
            offset={offset}
            limit={PAGE_SIZE}
            count={data.items.length}
            total={data.total}
            onChange={setOffset}
            emptyText="No events match."
          />
        )}
      </section>
    </>
  );
}

function TimelineTable({ items }) {
  return (
    <table>
      <thead>
        <tr>
          <th scope="col">Occurred</th>
          <th scope="col">Event</th>
          <th scope="col">Type</th>
          <th scope="col">Sources</th>
          <th scope="col">Events</th>
          <th scope="col">Evidence</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.cluster_id}>
            <td>{item.occurred_at ? formatTime(item.occurred_at) : "Date unknown"}</td>
            <td className="wrap">
              <Link to={`/event-clusters/${item.cluster_id}`}>{item.title}</Link>
            </td>
            <td>{item.event_type}</td>
            <td>
              {`${item.source_count}: `}
              {item.sources.map((source, index) => (
                <span key={source.source_id}>
                  {index > 0 && ", "}
                  <Link to={`/sources/${source.source_id}`}>{source.name}</Link>
                </span>
              ))}
            </td>
            <td>{item.event_count}</td>
            <td>{item.evidence_count}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
