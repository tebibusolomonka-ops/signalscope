import { useCallback, useState } from "react";
import { Link } from "react-router";

import { useOrganization } from "../../app/useOrganization.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { useResource } from "../../lib/useResource.js";
import { useSourceOptions } from "../sources/useSourceOptions.js";

// Browsers sometimes leave File.type empty; then the extension names the type.
const BY_EXTENSION = {
  txt: "text/plain",
  json: "application/json",
  htm: "text/html",
  html: "text/html",
  xhtml: "application/xhtml+xml",
  pdf: "application/pdf",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
};

function fileType(file) {
  if (file.type) return file.type;
  const extension = file.name.split(".").pop().toLowerCase();
  return BY_EXTENSION[extension] ?? "";
}

function megabytes(bytes) {
  return `${Math.round(bytes / (1024 * 1024))} MB`;
}

/** Why the API would refuse this file, or null. The API checks again. */
function problem(file, limits) {
  const type = fileType(file).split(";")[0].trim().toLowerCase();
  if (!limits.content_types.includes(type)) {
    return `${file.name} is not a supported file type.`;
  }
  if (file.size === 0) return `${file.name} is empty.`;
  if (file.size > limits.max_bytes) {
    return `${file.name} is larger than ${megabytes(limits.max_bytes)}.`;
  }
  return null;
}

/**
 * Store a file as a new document of an upload source in the active
 * organization. A processing worker parses it later.
 */
export function FileImportPage() {
  const { active, tenantApi, can } = useOrganization();
  const loadLimits = useCallback(() => tenantApi.get("/documents/files/limits"), [tenantApi]);
  const limits = useResource(loadLimits);
  const { sources, loaded, error: sourcesError } = useSourceOptions();
  const uploads = sources.filter((source) => source.type === "upload");

  return (
    <>
      <PageHeading title="Import a file">
        <span className="muted">{active.name}</span>
        <Link to="/documents">All documents</Link>
      </PageHeading>
      {!can.contribute && (
        <p className="muted">Your role in this organization cannot add documents.</p>
      )}
      {can.contribute && (
        <section className="panel" aria-labelledby="import-heading">
          <h2 id="import-heading">File</h2>
          {(limits.loading || !loaded) && <Loading />}
          <ErrorMessage error={limits.error ?? sourcesError} />
          {limits.data && loaded && uploads.length === 0 && (
            <p className="muted">
              Files are stored in an upload source, and this organization has none.{" "}
              {can.manage ? (
                <Link to="/sources">Add an upload source</Link>
              ) : (
                "Ask an owner or admin to add one."
              )}
            </p>
          )}
          {limits.data && uploads.length > 0 && (
            <ImportForm limits={limits.data} uploads={uploads} />
          )}
        </section>
      )}
    </>
  );
}

function ImportForm({ limits, uploads }) {
  const { tenantApi } = useOrganization();
  const [sourceId, setSourceId] = useState(uploads[0].id);
  const [file, setFile] = useState(null);
  const [state, setState] = useState({ busy: false, error: null, result: null });
  const refusal = file ? problem(file, limits) : null;

  function choose(event) {
    setFile(event.target.files[0] ?? null);
    setState({ busy: false, error: null, result: null });
  }

  async function submit(event) {
    event.preventDefault();
    if (!file || refusal) return;
    setState({ busy: true, error: null, result: null });
    try {
      const result = await tenantApi.upload("/documents/files", file, fileType(file), {
        query: { source_id: sourceId, filename: file.name },
      });
      setState({ busy: false, error: null, result });
    } catch (error) {
      setState({ busy: false, error, result: null });
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      <label>
        Upload source
        <select value={sourceId} onChange={(event) => setSourceId(event.target.value)}>
          {uploads.map((source) => (
            <option key={source.id} value={source.id}>
              {source.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        File
        <input
          type="file"
          accept={limits.content_types.join(",")}
          onChange={choose}
          aria-describedby="import-limits"
        />
      </label>
      <p id="import-limits" className="muted">
        {`Up to ${megabytes(limits.max_bytes)}. Types: ${limits.content_types.join(", ")}.`}
      </p>
      {file && !refusal && <p>{`Selected: ${file.name} (${file.size} bytes)`}</p>}
      {refusal && (
        <p className="error" role="alert">
          {refusal}
        </p>
      )}
      <ErrorMessage error={state.error} />
      <button type="submit" disabled={!file || Boolean(refusal) || state.busy}>
        {state.busy ? "Uploading..." : "Import file"}
      </button>
      {state.result && (
        <p role="status">
          {`${state.result.filename ?? "The file"} was stored and queued for processing. `}
          <Link to={`/documents/${state.result.document.id}`}>Open the document</Link>
        </p>
      )}
    </form>
  );
}
