import { formatTime } from "../../lib/format.js";

/** The item types in the order they are shown, with a plural heading. */
export const ITEM_TYPES = [
  ["source", "Sources"],
  ["document", "Documents"],
  ["event", "Events"],
  ["event_cluster", "Event clusters"],
  ["entity", "Entities"],
  ["claim", "Claims"],
  ["research_session", "Research sessions"],
];

const LINKS = {
  source: (id) => `/sources/${id}`,
  document: (id) => `/documents/${id}`,
  event_cluster: (id) => `/event-clusters/${id}`,
  entity: (id) => `/entities/${id}`,
  claim: (id) => `/claims/${id}`,
  research_session: (id) => `/research/${id}`,
};

function when(value) {
  return value ? formatTime(value) : "date unknown";
}

/**
 * How a saved item is shown, from its snapshot: the record as it was when it
 * was saved, never the live record. href is null when the app has no page
 * for the type.
 */
export function describeItem(item) {
  const snapshot = item.snapshot ?? {};
  const href = LINKS[item.item_type]?.(item.reference_id) ?? null;
  switch (item.item_type) {
    case "source":
      return { title: snapshot.name, detail: snapshot.source_type, href };
    case "document":
      return {
        title: snapshot.title || "Untitled document",
        detail: `published ${when(snapshot.published_at)}`,
        href,
      };
    case "event":
    case "event_cluster":
      return {
        title: snapshot.title,
        detail: `${snapshot.event_type}, ${when(snapshot.occurred_at)}`,
        href,
      };
    case "entity":
      return { title: snapshot.canonical_name, detail: snapshot.entity_type, href };
    case "claim":
      return { title: snapshot.text, detail: snapshot.claim_type, href };
    case "research_session":
      return {
        title: snapshot.title || "Untitled session",
        detail: `${snapshot.retrieval_mode}, ${snapshot.turn_count} turns when saved`,
        href,
      };
    default:
      return { title: item.reference_id, detail: item.item_type, href: null };
  }
}
