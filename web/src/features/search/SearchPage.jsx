import { useCallback } from "react";
import { Link, useSearchParams } from "react-router";

import { useOrganization } from "../../app/useOrganization.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { chunkLocation } from "../../lib/chunks.js";
import { useResource } from "../../lib/useResource.js";
import { SaveToInvestigation } from "../investigations/SaveToInvestigation.jsx";
import { useSourceOptions } from "../sources/useSourceOptions.js";

// Semantic and hybrid search name their embedding model. The API's local
// model is multilingual E5 small, the one reranked search always uses.
const EMBEDDING = { provider: "sentence_transformers", model: "intfloat/multilingual-e5-small" };

const MODES = {
  hybrid: { label: "Hybrid", path: "/search/hybrid", embedding: true },
  lexical: { label: "Lexical (full text)", path: "/search", embedding: false },
  semantic: { label: "Semantic", path: "/search/semantic", embedding: true },
  reranked: { label: "Reranked", path: "/search/reranked", embedding: false },
};
const LIMITS = [10, 25, 50];

/**
 * Search the active organization's documents in any of the four modes.
 *
 * The query is kept in the URL together with the organization it was made
 * in, so after switching organization the old search is not run again.
 * Results are shown in the order the API returns them.
 */
export function SearchPage() {
  const { active } = useOrganization();
  const { sources, names } = useSourceOptions();
  const [params, setParams] = useSearchParams();
  const current = params.get("org") === active.id;
  const search = {
    q: current ? (params.get("q") ?? "") : "",
    mode: current && MODES[params.get("mode")] ? params.get("mode") : "hybrid",
    source_id: current ? (params.get("source_id") ?? "") : "",
    limit:
      current && LIMITS.includes(Number(params.get("limit"))) ? Number(params.get("limit")) : 10,
  };

  function submit(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const next = { org: active.id, q: form.get("q").trim(), mode: form.get("mode") };
    if (form.get("source_id")) next.source_id = form.get("source_id");
    if (form.get("limit") !== "10") next.limit = form.get("limit");
    setParams(next);
  }

  return (
    <>
      <PageHeading title="Search">
        <span className="muted">{active.name}</span>
      </PageHeading>
      <SearchForm key={params.toString()} search={search} sources={sources} onSubmit={submit} />
      {search.q && <Results search={search} names={names} />}
    </>
  );
}

function SearchForm({ search, sources, onSubmit }) {
  return (
    <section className="panel" aria-labelledby="search-form">
      <h2 id="search-form">Query</h2>
      <form className="form-row" role="search" aria-label="Search documents" onSubmit={onSubmit}>
        <label className="grow">
          Search for
          <input name="q" required maxLength={1000} defaultValue={search.q} />
        </label>
        <label>
          Mode
          <select name="mode" defaultValue={search.mode}>
            {Object.entries(MODES).map(([value, mode]) => (
              <option key={value} value={value}>
                {mode.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Source
          <select name="source_id" defaultValue={search.source_id}>
            <option value="">All sources</option>
            {sources.map((source) => (
              <option key={source.id} value={source.id}>
                {source.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Results
          <select name="limit" defaultValue={String(search.limit)}>
            {LIMITS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <button type="submit">Search</button>
      </form>
    </section>
  );
}

function Results({ search, names }) {
  const { tenantApi } = useOrganization();
  const { q, mode, source_id, limit } = search;
  const load = useCallback(() => {
    const spec = MODES[mode];
    const query = { q, source_id, limit, ...(spec.embedding ? EMBEDDING : {}) };
    return tenantApi.get(spec.path, { query });
  }, [tenantApi, q, mode, source_id, limit]);
  const { data, error, loading } = useResource(load);

  return (
    <section className="panel" aria-labelledby="search-results" aria-busy={loading}>
      <h2 id="search-results">Results</h2>
      {loading && <Loading label="Searching..." />}
      {error?.status === 503 ? (
        <p className="error" role="alert">
          {`${MODES[mode].label} search is not available: ${error.message} It needs a model that is not enabled on the server. Lexical search works without one.`}
        </p>
      ) : (
        <ErrorMessage error={error} />
      )}
      {data && data.items.length === 0 && <p className="muted">No results.</p>}
      {data && data.items.length > 0 && (
        <ol className="results">
          {data.items.map((item) => (
            <Result
              key={item.chunk_id}
              item={item}
              mode={mode}
              sourceName={names.get(item.source_id)}
            />
          ))}
        </ol>
      )}
    </section>
  );
}

function score(value, digits = 4) {
  return Number(value).toFixed(digits);
}

/** The values the API returned for one result, labelled by what they are. */
function scores(item, mode) {
  if (mode === "lexical") return [["Lexical score", score(item.rank)]];
  if (mode === "semantic") return [["Semantic similarity", score(item.similarity)]];
  const values = [];
  if (mode === "reranked") values.push(["Reranker score", score(item.reranker_score)]);
  values.push(["Hybrid score", score(item.hybrid_score)]);
  if (item.lexical_rank !== null && item.lexical_rank !== undefined) {
    values.push(["Lexical position", String(item.lexical_rank)]);
  }
  if (item.vector_similarity !== null && item.vector_similarity !== undefined) {
    values.push(["Semantic similarity", score(item.vector_similarity)]);
  }
  return values;
}

function Result({ item, mode, sourceName }) {
  const location = chunkLocation(item.chunk_metadata);
  return (
    <li className="result">
      <h3>
        <Link to={`/documents/${item.document_id}`}>{item.title || "Untitled document"}</Link>
      </h3>
      <p className="muted">
        <Link to={`/sources/${item.source_id}`}>{sourceName ?? "Source"}</Link>
        {location && ` · ${location}`}
      </p>
      {item.excerpt && <p>{item.excerpt}</p>}
      <SaveToInvestigation itemType="document" referenceId={item.document_id} />
      <dl className="scores">
        {scores(item, mode).map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </li>
  );
}
