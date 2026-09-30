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

export function hit(overrides = {}) {
  return {
    document_id: "d-1",
    chunk_id: "c-1",
    source_id: "s-1",
    title: "Storm closes the harbour",
    url: "https://harbour.example/storm",
    excerpt: "The harbour closed at noon after the storm.",
    chunk_metadata: { page_number: 2, section_kind: "page", section_index: 1 },
    ...overrides,
  };
}

export function entity(overrides = {}) {
  return {
    id: "e-1",
    canonical_name: "Harbour Authority",
    normalized_name: "harbour authority",
    entity_type: "organization",
    mention_count: 3,
    created_at: "2026-09-05T07:00:00Z",
    ...overrides,
  };
}

/** One mention or evidence row of an entity or claim. */
export function evidence(overrides = {}) {
  return {
    id: "m-1",
    document_id: "d-1",
    document_title: "Storm closes the harbour",
    source_id: "s-1",
    source_name: "Harbour Feed",
    chunk_id: "c-1",
    surface_text: "the Harbour Authority",
    start_char: 10,
    end_char: 31,
    confidence: 0.912,
    provider: "gliner",
    model: "urchade/gliner_multi-v2.1",
    chunk_metadata: { page_number: 2 },
    ...overrides,
  };
}

export function investigation(overrides = {}) {
  return {
    id: "inv-1",
    title: "Harbour closure",
    description: "Why the harbour closed.",
    status: "open",
    organization_id: "org-a",
    created_by_user_id: "u-admin",
    created_at: "2026-09-10T08:00:00Z",
    updated_at: "2026-09-11T08:00:00Z",
    ...overrides,
  };
}

export function savedItem(type, snapshot, overrides = {}) {
  return {
    id: `item-${type}`,
    item_type: type,
    reference_id: `ref-${type}`,
    label: null,
    snapshot,
    created_at: "2026-09-12T08:00:00Z",
    ...overrides,
  };
}

export function researchSession(overrides = {}) {
  return {
    id: "rs-1",
    title: "Closure questions",
    retrieval_mode: "hybrid",
    source_id: null,
    organization_id: "org-a",
    created_at: "2026-09-12T08:00:00Z",
    updated_at: "2026-09-12T09:00:00Z",
    ...overrides,
  };
}

/** One numbered evidence piece of a research turn, context or answer. */
export function researchEvidence(id, overrides = {}) {
  return {
    evidence_id: id,
    document_id: `d-${id}`,
    chunk_id: `c-${id}`,
    source_id: "s-1",
    title: `Report ${id}`,
    url: null,
    excerpt: `Excerpt of ${id}.`,
    chunk_metadata: { page_number: 1 },
    ...overrides,
  };
}

export function turn(sequence, overrides = {}) {
  const evidence = [researchEvidence("E1"), researchEvidence("E2")];
  return {
    id: `t-${sequence}`,
    sequence,
    question: `Question number ${sequence}?`,
    answer: "The harbour closed [E1].",
    citation_ids: ["E1"],
    citations: [evidence[0]],
    evidence,
    created_at: "2026-09-12T08:00:00Z",
    ...overrides,
  };
}
