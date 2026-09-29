import { useState } from "react";
import { Link } from "react-router";

import { useOrganization } from "../../app/useOrganization.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { formatTime } from "../../lib/format.js";
import { useSourceOptions } from "./useSourceOptions.js";

const MIN = 2;
const MAX = 10;

// The observed values of each source, in the order they are shown.
const SIGNALS = [
  ["document_count", "Documents"],
  ["first_document_at", "First document stored", formatTime],
  ["last_document_at", "Last document stored", formatTime],
  ["first_published_at", "First published", formatTime],
  ["last_published_at", "Last published", formatTime],
  ["revision_count", "Document revisions"],
  ["entity_count", "Entities"],
  ["claim_count", "Claims"],
  ["event_count", "Events"],
  ["event_cluster_count", "Event clusters"],
  ["cross_source_event_cluster_count", "Event clusters also reported by other sources"],
];

/**
 * Two to ten sources of the active organization side by side.
 *
 * Only observed counts and dates: no score, ranking or winner.
 */
export function SourceComparePage() {
  const { active, tenantApi } = useOrganization();
  const { sources, loaded, error: sourcesError } = useSourceOptions();
  const [selected, setSelected] = useState([]);
  const [state, setState] = useState({ busy: false, error: null, result: null });

  function toggle(sourceId) {
    setSelected((current) =>
      current.includes(sourceId) ? current.filter((id) => id !== sourceId) : [...current, sourceId],
    );
  }

  async function compare(event) {
    event.preventDefault();
    setState({ busy: true, error: null, result: null });
    try {
      const result = await tenantApi.post("/sources/compare", {
        source_ids: selected,
        organization_id: tenantApi.organizationId,
      });
      setState({ busy: false, error: null, result });
    } catch (error) {
      setState({ busy: false, error, result: null });
    }
  }

  const count = selected.length;
  const hint =
    count < MIN ? `Choose at least ${MIN} sources.` : `${count} of at most ${MAX} sources chosen.`;

  return (
    <>
      <PageHeading title="Compare sources">
        <span className="muted">{active.name}</span>
        <Link to="/sources">All sources</Link>
      </PageHeading>
      <section className="panel" aria-labelledby="compare-choose">
        <h2 id="compare-choose">Sources</h2>
        {!loaded && <Loading />}
        <ErrorMessage error={sourcesError} />
        {loaded && sources.length < MIN && (
          <p className="muted">This organization needs at least two sources to compare.</p>
        )}
        {loaded && sources.length >= MIN && (
          <form onSubmit={compare}>
            <fieldset className="choices">
              <legend>{`Choose ${MIN} to ${MAX} sources`}</legend>
              {sources.map((source) => (
                <label key={source.id} className="choice">
                  <input
                    type="checkbox"
                    checked={selected.includes(source.id)}
                    disabled={!selected.includes(source.id) && count >= MAX}
                    onChange={() => toggle(source.id)}
                  />
                  {`${source.name} (${source.type})`}
                </label>
              ))}
            </fieldset>
            <p className="muted" aria-live="polite">
              {hint}
            </p>
            <button type="submit" disabled={count < MIN || state.busy}>
              {state.busy ? "Comparing..." : "Compare"}
            </button>
          </form>
        )}
        <ErrorMessage error={state.error} />
      </section>
      {state.result && <Comparison result={state.result} />}
    </>
  );
}

function Comparison({ result }) {
  return (
    <section className="panel" aria-labelledby="compare-result">
      <h2 id="compare-result">Side by side</h2>
      <p className="muted">
        Observed counts and dates for each source in this organization. They describe the sources;
        they do not score or rank them.
      </p>
      <div className="scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">Observed</th>
              {result.sources.map(({ source }) => (
                <th scope="col" key={source.id}>
                  <Link to={`/sources/${source.id}`}>{source.name}</Link>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {SIGNALS.map(([key, label, format]) => (
              <tr key={key}>
                <th scope="row">{label}</th>
                {result.sources.map(({ source, provenance }) => (
                  <td key={source.id}>{format ? format(provenance[key]) : provenance[key]}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3>In common</h3>
      <dl className="facts">
        <dt>Event clusters reported by two or more of these sources</dt>
        <dd>{result.shared_event_cluster_count}</dd>
        <dt>Entities found in two or more of these sources</dt>
        <dd>{result.shared_entity_count}</dd>
        <dt>Claims found in two or more of these sources</dt>
        <dd>{result.shared_claim_count}</dd>
      </dl>
    </section>
  );
}
