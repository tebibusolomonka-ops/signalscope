/** Small factories for organization content answers in page tests. */
export function page(items, { total = items.length, limit = 50, offset = 0 } = {}) {
  return { body: { items, total, limit, offset } };
}

export function source(overrides = {}) {
  return {
    id: "s-1",
    type: "rss",
    name: "Harbour Feed",
    url: "https://harbour.example/feed.xml",
    ingestion_enabled: false,
    ingestion_interval_minutes: null,
    next_ingestion_at: null,
    organization_id: "org-a",
    created_at: "2026-09-01T08:00:00Z",
    updated_at: "2026-09-02T08:00:00Z",
    ...overrides,
  };
}

/** Answer after release() is called, to hold a request while a test looks at the page. */
export function held() {
  let release;
  const ready = new Promise((resolve) => {
    release = resolve;
  });
  return { ready, release };
}
