import { useCallback, useState } from "react";

import { useAuth } from "../../app/useAuth.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { Pager } from "../../components/Pager.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { formatTime } from "../../lib/format.js";
import { useResource } from "../../lib/useResource.js";

const PAGE_SIZE = 50;
const TASKS = [
  "embedding_retrieval",
  "reranking",
  "structured_extraction",
  "answer_citation",
  "relation_evaluation",
];

/**
 * Stored evaluation reports, for system admins. Measured reports are imported
 * as JSON; models are never run from the browser. Comparisons show factual
 * deltas only, with no winner or recommendation.
 */
export function EvaluationsPage() {
  const { user } = useAuth();
  if (!user?.is_system_admin) {
    return (
      <>
        <PageHeading title="Evaluations" />
        <p className="muted">Only system admins can review evaluation reports.</p>
      </>
    );
  }
  return <Evaluations />;
}

function Evaluations() {
  const { api } = useAuth();
  const [task, setTask] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState(null);
  const [chosen, setChosen] = useState([]);
  const load = useCallback(
    () => api.get("/admin/evaluations", { query: { task, limit: PAGE_SIZE, offset } }),
    [api, task, offset],
  );
  const { data, error, loading, reload } = useResource(load);

  function toggle(id) {
    setChosen((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );
  }

  return (
    <>
      <PageHeading title="Evaluations" />
      <section className="panel" aria-labelledby="evaluations-heading">
        <h2 id="evaluations-heading">Reports</h2>
        <p className="muted">
          Measured benchmark reports kept for review. Importing stores a report; it does not run a
          model.
        </p>
        <label className="inline">
          Task
          <select
            value={task}
            onChange={(event) => {
              setOffset(0);
              setTask(event.target.value);
            }}
          >
            <option value="">All tasks</option>
            {TASKS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        {loading && <Loading />}
        <ErrorMessage error={error} />
        {data && data.items.length > 0 && (
          <table>
            <thead>
              <tr>
                <th scope="col">Compare</th>
                <th scope="col">Task</th>
                <th scope="col">Model</th>
                <th scope="col">Provider</th>
                <th scope="col">Dataset</th>
                <th scope="col">Imported</th>
                <th scope="col">Detail</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((report) => (
                <tr key={report.id}>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`Compare ${report.model}`}
                      checked={chosen.includes(report.id)}
                      onChange={() => toggle(report.id)}
                    />
                  </td>
                  <td>{report.task}</td>
                  <td>{report.model}</td>
                  <td>{report.provider}</td>
                  <td>{report.dataset_name || report.dataset_fingerprint}</td>
                  <td>{formatTime(report.created_at)}</td>
                  <td>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => setSelected(report.id)}
                    >
                      View
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {data && (
          <Pager
            offset={offset}
            limit={PAGE_SIZE}
            count={data.items.length}
            total={data.total}
            onChange={setOffset}
            emptyText="No evaluation reports yet."
          />
        )}
      </section>
      {chosen.length >= 2 && <Comparison reportIds={chosen} />}
      {selected && <ReportDetail key={selected} reportId={selected} />}
      <ImportReport onImported={reload} />
    </>
  );
}

function ReportDetail({ reportId }) {
  const { api } = useAuth();
  const load = useCallback(() => api.get(`/admin/evaluations/${reportId}`), [api, reportId]);
  const { data, error, loading } = useResource(load);
  const report = data?.report_json;

  return (
    <section className="panel" aria-labelledby="report-detail">
      <h2 id="report-detail">Report detail</h2>
      {loading && <Loading />}
      <ErrorMessage error={error} />
      {data && (
        <>
          <dl className="facts">
            <dt>Task</dt>
            <dd>{data.task}</dd>
            <dt>Model</dt>
            <dd>{data.model}</dd>
            <dt>Provider</dt>
            <dd>{data.provider}</dd>
            <dt>Dataset</dt>
            <dd>{`${data.dataset_name} (${data.dataset_fingerprint})`}</dd>
          </dl>
          {data.task === "relation_evaluation" && (
            <p className="notice" role="note">
              Relation evaluation only. Relation persistence is not enabled.
            </p>
          )}
          <Facts title="Metrics" values={report?.metrics} />
          <Facts title="Timings" values={report?.timings} />
          {Array.isArray(report?.warnings) && report.warnings.length > 0 && (
            <>
              <h3>Warnings</h3>
              <ul>
                {report.warnings.map((warning, index) => (
                  <li key={index}>{warning}</li>
                ))}
              </ul>
            </>
          )}
          <Facts title="Environment" values={data.environment_summary} />
        </>
      )}
    </section>
  );
}

function Facts({ title, values }) {
  const entries = values && typeof values === "object" ? Object.entries(values) : [];
  if (entries.length === 0) return null;
  return (
    <>
      <h3>{title}</h3>
      <dl className="facts">
        {entries.map(([key, value]) => (
          <div key={key} className="fact-pair">
            <dt>{key}</dt>
            <dd>{typeof value === "object" ? JSON.stringify(value) : String(value)}</dd>
          </div>
        ))}
      </dl>
    </>
  );
}

function Comparison({ reportIds }) {
  const { api } = useAuth();
  const load = useCallback(
    () => api.post("/admin/evaluations/compare", { report_ids: reportIds }),
    [api, reportIds],
  );
  const { data, error, loading } = useResource(load);

  return (
    <section className="panel" aria-labelledby="comparison">
      <h2 id="comparison">Comparison</h2>
      <p className="muted">Factual differences between the chosen reports. No report is ranked.</p>
      {loading && <Loading />}
      {error?.status === 422 ? (
        <p className="error" role="alert">
          {error.message}
        </p>
      ) : (
        <ErrorMessage error={error} />
      )}
      {data && (
        <table>
          <thead>
            <tr>
              <th scope="col">Metric</th>
              {data.reports.map((id) => (
                <th scope="col" key={id}>
                  {id.slice(0, 8)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Object.entries(data.metrics).map(([name, series]) => (
              <tr key={name}>
                <th scope="row">{name}</th>
                {series.values.map((value, index) => (
                  <td key={index}>
                    {value}
                    {index > 0 &&
                      ` (${series.deltas[index] >= 0 ? "+" : ""}${series.deltas[index]})`}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function ImportReport({ onImported }) {
  const { api } = useAuth();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(null);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setDone(null);
    let report;
    try {
      report = JSON.parse(text);
    } catch {
      setError({ message: "That is not valid JSON." });
      setBusy(false);
      return;
    }
    try {
      const record = await api.post("/admin/evaluations/import", { report });
      setDone(record);
      setText("");
      onImported();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="import-report">
      <h2 id="import-report">Import a report</h2>
      <p className="muted">Paste a completed evaluation report JSON. Models are never run here.</p>
      <form className="form" onSubmit={submit}>
        <label>
          Report JSON
          <textarea rows={6} value={text} onChange={(event) => setText(event.target.value)} />
        </label>
        <ErrorMessage error={error} />
        {done && <p role="status">{`Stored report for ${done.model} (${done.task}).`}</p>}
        <button type="submit" disabled={busy || !text.trim()}>
          {busy ? "Importing..." : "Import report"}
        </button>
      </form>
    </section>
  );
}
