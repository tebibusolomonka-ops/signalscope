import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router";

import { useOrganization } from "../../app/useOrganization.js";
import { ExportActions } from "../../components/ExportActions.jsx";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { formatTime } from "../../lib/format.js";
import { useResource } from "../../lib/useResource.js";
import { SaveToInvestigation } from "../investigations/SaveToInvestigation.jsx";
import { useSourceOptions } from "../sources/useSourceOptions.js";
import { AnswerText, EvidenceCard } from "./Evidence.jsx";
import { focusEvidence } from "./evidenceFocus.js";

const DEFAULT_LIMIT = 8;
const MAX_LIMIT = 20;
const TURN_PAGE_SIZE = 50;

/**
 * One research session: the conversation so far, the evidence of one turn,
 * and a form for the next question.
 *
 * Earlier answers are shown as conversation, never as evidence. A session of
 * another organization is treated as not found here.
 */
export function ResearchSessionPage() {
  const { sessionId } = useParams();
  const { active, tenantApi } = useOrganization();
  const load = useCallback(async () => {
    const session = await tenantApi.get(`/research/sessions/${sessionId}`);
    if (session.organization_id !== active.id) return { elsewhere: true };
    const turns = await tenantApi.get(`/research/sessions/${sessionId}/turns`, {
      query: { limit: TURN_PAGE_SIZE },
    });
    return { session, turns };
  }, [tenantApi, sessionId, active.id]);
  const { data, error, loading } = useResource(load);

  return (
    <>
      <PageHeading title={data?.session ? data.session.title || "Untitled session" : "Research"}>
        <Link to="/research">All sessions</Link>
      </PageHeading>
      {loading && <Loading />}
      <ErrorMessage error={error} />
      {data?.elsewhere && (
        <p className="error" role="alert">
          This research session does not belong to the active organization.
        </p>
      )}
      {data?.session && (
        <Session
          session={data.session}
          initialTurns={data.turns.items}
          initialTotal={data.turns.total}
        />
      )}
    </>
  );
}

function Session({ session, initialTurns, initialTotal }) {
  const { tenantApi, can } = useOrganization();
  const { names } = useSourceOptions();
  const [turns, setTurns] = useState(initialTurns);
  const [total, setTotal] = useState(initialTotal);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState(null);
  const [selectedId, setSelectedId] = useState(initialTurns.at(-1)?.id ?? null);
  const [pending, setPending] = useState(null);
  const [focus, setFocus] = useState(null);
  const selected = turns.find((turn) => turn.id === selectedId) ?? null;

  async function loadMore() {
    setLoadingMore(true);
    setMoreError(null);
    try {
      const next = await tenantApi.get(`/research/sessions/${session.id}/turns`, {
        query: { limit: TURN_PAGE_SIZE, offset: turns.length },
      });
      setTotal(next.total);
      setTurns((current) => {
        const seen = new Set(current.map((turn) => turn.id));
        return [...current, ...next.items.filter((turn) => !seen.has(turn.id))];
      });
    } catch (failure) {
      setMoreError(failure);
    } finally {
      setLoadingMore(false);
    }
  }

  useEffect(() => {
    if (focus) focusEvidence(focus.turnId, focus.evidenceId);
  }, [focus]);

  function cite(turn, evidenceId) {
    setSelectedId(turn.id);
    // A new object each time, so the same citation can be followed again.
    setFocus({ turnId: turn.id, evidenceId });
  }

  function added(turn) {
    setTurns((current) =>
      current.some((item) => item.id === turn.id) ? current : [...current, turn],
    );
    setTotal((current) => current + 1);
    setSelectedId(turn.id);
    setPending(null);
  }

  return (
    <>
      <section className="panel" aria-labelledby="session-settings">
        <h2 id="session-settings">Session</h2>
        <dl className="facts">
          <dt>Retrieval mode</dt>
          <dd>{session.retrieval_mode}</dd>
          <dt>Sources searched</dt>
          <dd>
            {session.source_id ? (
              <Link to={`/sources/${session.source_id}`}>
                {names.get(session.source_id) ?? "One source"}
              </Link>
            ) : (
              "All sources of this organization"
            )}
          </dd>
          <dt>Started</dt>
          <dd>{formatTime(session.created_at)}</dd>
        </dl>
        <div className="page-actions">
          <SaveToInvestigation itemType="research_session" referenceId={session.id} />
        </div>
        <ExportActions
          path={`/research/sessions/${session.id}/export`}
          kind="research-session"
          id={session.id}
        />
      </section>
      <div className="research-layout">
        <section className="panel" aria-labelledby="conversation">
          <h2 id="conversation">Conversation</h2>
          {turns.length === 0 && !pending && <p className="muted">No questions asked yet.</p>}
          <ol className="turns">
            {turns.map((turn) => (
              <Turn
                key={turn.id}
                turn={turn}
                selected={turn.id === selectedId}
                onSelect={() => setSelectedId(turn.id)}
                onCite={(evidenceId) => cite(turn, evidenceId)}
              />
            ))}
            {pending && (
              <li className="turn pending" aria-busy="true">
                <p className="question">{pending}</p>
                <p role="status">Searching and answering...</p>
              </li>
            )}
          </ol>
          {turns.length < total && (
            <button type="button" className="secondary" onClick={loadMore} disabled={loadingMore}>
              {loadingMore ? "Loading..." : `Load more turns (${total - turns.length} left)`}
            </button>
          )}
          <ErrorMessage error={moreError} />
          {can.contribute ? (
            <AskForm
              sessionId={session.id}
              busy={pending !== null}
              onAsk={setPending}
              onAdded={added}
              onFailed={() => setPending(null)}
            />
          ) : (
            <p className="muted">Your role in this organization cannot ask questions here.</p>
          )}
        </section>
        <section className="panel" aria-labelledby="turn-evidence">
          <h2 id="turn-evidence">Evidence</h2>
          {!selected && <p className="muted">Evidence appears here after a question.</p>}
          {selected && (
            <>
              <p className="muted">
                {`What turn ${selected.sequence} was answered from, as saved then: "${selected.question}"`}
              </p>
              {selected.evidence.length === 0 && (
                <p className="muted">No evidence was found for this question.</p>
              )}
              <ol className="evidence-list">
                {selected.evidence.map((item) => (
                  <EvidenceCard
                    key={item.evidence_id}
                    item={item}
                    scope={selected.id}
                    sourceName={names.get(item.source_id)}
                    cited={selected.citation_ids.includes(item.evidence_id)}
                  />
                ))}
              </ol>
            </>
          )}
        </section>
      </div>
    </>
  );
}

function Turn({ turn, selected, onSelect, onCite }) {
  return (
    <li className={selected ? "turn selected" : "turn"}>
      <p className="question">
        <span className="muted">{`Question ${turn.sequence} · ${formatTime(turn.created_at)}`}</span>
        <br />
        {turn.question}
      </p>
      <div className="answer">
        {turn.answer !== null ? (
          <AnswerText text={turn.answer} onCite={onCite} />
        ) : (
          <p className="muted">
            {turn.evidence.length > 0
              ? "Evidence collected; no answer model is configured, so no answer was written."
              : "No evidence was found, so no answer was written."}
          </p>
        )}
        {turn.citation_ids.length > 0 && (
          <p className="muted">
            {"Cites: "}
            {turn.citation_ids.map((id) => (
              <button
                key={id}
                type="button"
                className="cite"
                aria-label={`Show evidence ${id}`}
                onClick={() => onCite(id)}
              >
                {id}
              </button>
            ))}
          </p>
        )}
      </div>
      <button type="button" className="secondary" aria-pressed={selected} onClick={onSelect}>
        {`Show evidence (${turn.evidence.length})`}
      </button>
    </li>
  );
}

function AskForm({ sessionId, busy, onAsk, onAdded, onFailed }) {
  const { tenantApi } = useOrganization();
  const [question, setQuestion] = useState("");
  const [limit, setLimit] = useState(String(DEFAULT_LIMIT));
  const [error, setError] = useState(null);

  async function submit(event) {
    event.preventDefault();
    const asked = question.trim();
    if (!asked) return;
    setError(null);
    onAsk(asked);
    try {
      const answer = await tenantApi.post(`/research/sessions/${sessionId}/turns`, {
        question: asked,
        limit: Number(limit),
      });
      setQuestion("");
      onAdded(answer.turn);
    } catch (failure) {
      setError(failure);
      onFailed();
    }
  }

  return (
    <form className="form" onSubmit={submit} aria-label="Ask a question">
      <label>
        Question
        <textarea
          rows={3}
          required
          maxLength={1000}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
        />
      </label>
      <label>
        Evidence pieces
        <input
          type="number"
          min={1}
          max={MAX_LIMIT}
          value={limit}
          onChange={(event) => setLimit(event.target.value)}
        />
      </label>
      <ErrorMessage error={error} />
      <button type="submit" disabled={busy}>
        {busy ? "Asking..." : "Ask"}
      </button>
    </form>
  );
}
