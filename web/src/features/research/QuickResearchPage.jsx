import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";

import { useOrganization } from "../../app/useOrganization.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage } from "../../components/Status.jsx";
import { SourcePicker } from "../sources/SourcePicker.jsx";
import { useSourceOptions } from "../sources/useSourceOptions.js";
import { AnswerText, EvidenceCard } from "./Evidence.jsx";
import { focusEvidence } from "./evidenceFocus.js";
import { RESEARCH_MODES } from "./modes.js";

const SCOPE = "quick";

/**
 * One question without a saved session: collect the evidence, or also ask
 * the answer model. Nothing here is stored.
 */
export function QuickResearchPage() {
  const { active, tenantApi } = useOrganization();
  const navigate = useNavigate();
  const sourceOptions = useSourceOptions();
  const { names } = sourceOptions;
  const [state, setState] = useState({ busy: null, error: null, result: null });
  const [focus, setFocus] = useState(null);
  const mounted = useRef(true);
  // Which submit button was pressed: collect evidence, or also answer.
  const chosen = useRef("context");

  useEffect(() => {
    if (focus) focusEvidence(SCOPE, focus.evidenceId);
  }, [focus]);

  useEffect(
    () => () => {
      mounted.current = false;
    },
    [],
  );

  async function run(event) {
    event.preventDefault();
    const action = chosen.current;
    const form = new FormData(event.currentTarget);
    const body = {
      query: form.get("query").trim(),
      mode: form.get("mode"),
      limit: Number(form.get("limit")),
      organization_id: tenantApi.organizationId,
    };
    if (form.get("source_id")) body.source_id = form.get("source_id");
    setState({ busy: action, error: null, result: null });
    try {
      if (action === "start") {
        const start = {
          question: body.query,
          retrieval_mode: body.mode,
          organization_id: body.organization_id,
        };
        if (body.source_id) start.source_id = body.source_id;
        if (form.get("title").trim()) start.title = form.get("title").trim();
        const result = await tenantApi.post("/research/sessions/start", start);
        if (mounted.current) navigate(`/research/${result.session.id}`);
        return;
      }
      const answer = await tenantApi.post(`/research/${action}`, body);
      if (mounted.current) setState({ busy: null, error: null, result: { action, ...answer } });
    } catch (error) {
      if (mounted.current) setState({ busy: null, error: { action, error }, result: null });
    }
  }

  const result = state.result;
  return (
    <>
      <PageHeading title="Quick research">
        <span className="muted">{active.name}</span>
        <Link to="/research">Research sessions</Link>
      </PageHeading>
      <section className="panel" aria-labelledby="quick-question">
        <h2 id="quick-question">Question</h2>
        <p className="muted">
          Collect one-off evidence and answers, or start a saved session with this question.
        </p>
        <form className="form" onSubmit={run} aria-label="Research question">
          <label>
            Question
            <textarea name="query" rows={3} required maxLength={1000} />
          </label>
          <label>
            Session title (optional)
            <input name="title" maxLength={200} />
          </label>
          <div className="form-row">
            <label>
              Mode
              <select name="mode" defaultValue="hybrid">
                {RESEARCH_MODES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <SourcePicker options={sourceOptions} />
            <label>
              Evidence pieces
              <input name="limit" type="number" min={1} max={20} defaultValue={8} />
            </label>
          </div>
          <div className="form-row">
            <button
              type="submit"
              disabled={state.busy !== null}
              onClick={() => (chosen.current = "context")}
            >
              {state.busy === "context" ? "Collecting..." : "Collect evidence"}
            </button>
            <button
              type="submit"
              disabled={state.busy !== null}
              onClick={() => (chosen.current = "answer")}
            >
              {state.busy === "answer" ? "Answering..." : "Collect evidence and answer"}
            </button>
            <button
              type="submit"
              disabled={state.busy !== null}
              onClick={() => (chosen.current = "start")}
            >
              {state.busy === "start" ? "Starting..." : "Start research session"}
            </button>
          </div>
        </form>
        {state.error && <Failure {...state.error} />}
      </section>
      {result?.action === "answer" && (
        <section className="panel" aria-labelledby="quick-answer">
          <h2 id="quick-answer">Answer</h2>
          {result.answer ? (
            <>
              <AnswerText
                text={result.answer.text}
                onCite={(evidenceId) => setFocus({ evidenceId })}
              />
              <p className="muted">
                {`Cites ${result.citations.length} of ${result.evidence.length} evidence pieces.`}
              </p>
            </>
          ) : (
            <p className="muted">No evidence was found, so no answer was written.</p>
          )}
        </section>
      )}
      {result && (
        <section className="panel" aria-labelledby="quick-evidence">
          <h2 id="quick-evidence">Evidence</h2>
          <p className="muted">{`For "${result.query}" (${result.mode}).`}</p>
          {result.evidence.length === 0 && (
            <p className="muted">No evidence was found in this organization.</p>
          )}
          <ol className="evidence-list">
            {result.evidence.map((item) => (
              <EvidenceCard
                key={item.evidence_id}
                item={item}
                scope={SCOPE}
                sourceName={names.get(item.source_id)}
                cited={
                  result.action === "answer" &&
                  (result.answer?.citation_ids ?? []).includes(item.evidence_id)
                }
              />
            ))}
          </ol>
        </section>
      )}
    </>
  );
}

function Failure({ action, error }) {
  if (error.status !== 503) return <ErrorMessage error={error} />;
  if (action === "start") return <ErrorMessage error={error} />;
  const text =
    action === "answer"
      ? "No answer model is enabled on the server, so answers cannot be written. Collecting evidence still works."
      : "This retrieval mode needs a model that is not enabled on the server. Lexical mode works without one.";
  return (
    <p className="error" role="alert">
      {`${text} (${error.message})`}
    </p>
  );
}
