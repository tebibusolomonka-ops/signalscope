/** Fake answers for the three dashboard routes. */
export const DASHBOARD_ROUTES = {
  "GET /dashboard/overview": {
    body: { sources: 3, documents: 120, pending_ingestion: 2 },
  },
  "GET /dashboard/sources": {
    body: {
      days: 14,
      source_id: null,
      items: [{ date: "2026-10-01", documents_created: 5, documents_published: 4 }],
    },
  },
  "GET /dashboard/events": {
    body: {
      days: 14,
      event_type: null,
      source_id: null,
      items: [{ date: "2026-10-01", events: 7, clusters: 3, cross_source_clusters: 1 }],
    },
  },
};
