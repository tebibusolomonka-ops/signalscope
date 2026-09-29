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

export function provenance(overrides = {}) {
  return {
    source_id: "s-1",
    document_count: 12,
    first_document_at: "2026-09-01T08:00:00Z",
    last_document_at: "2026-09-20T08:00:00Z",
    first_published_at: null,
    last_published_at: null,
    entity_count: 30,
    claim_count: 7,
    event_count: 5,
    event_cluster_count: 4,
    cross_source_event_cluster_count: 2,
    revision_count: 3,
    ...overrides,
  };
}

export function notFound(message = "Not found.") {
  return { status: 404, body: { error: { code: "not_found", message } } };
}

export function forbidden(message = "You do not have permission to do this.") {
  return { status: 403, body: { error: { code: "forbidden", message } } };
}

export function run(overrides = {}) {
  return {
    id: "r-1",
    source_id: "s-1",
    status: "completed",
    started_at: "2026-09-10T08:00:05Z",
    finished_at: "2026-09-10T08:00:30Z",
    error_message: null,
    items_seen: 20,
    documents_created: 4,
    duplicates_skipped: 16,
    attempt_count: 1,
    created_at: "2026-09-10T08:00:00Z",
    updated_at: "2026-09-10T08:00:30Z",
    ...overrides,
  };
}

export function doc(overrides = {}) {
  return {
    id: "d-1",
    source_id: "s-1",
    external_id: null,
    url: "https://harbour.example/storm",
    title: "Storm closes the harbour",
    content: "The harbour closed at noon.",
    language: "en",
    published_at: "2026-09-05T06:00:00Z",
    created_at: "2026-09-05T07:00:00Z",
    updated_at: "2026-09-05T07:00:00Z",
    ...overrides,
  };
}

export function revision(version, overrides = {}) {
  return {
    version,
    title: "Storm closes the harbour",
    language: "en",
    url: "https://harbour.example/storm",
    content_hash: "abcdef0123456789",
    content_length: 24,
    created_at: `2026-09-0${version}T07:00:00Z`,
    ...overrides,
  };
}
