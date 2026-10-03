import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { useOrganization } from "../../app/useOrganization.js";
import { ConfirmAction } from "../../components/ConfirmAction.jsx";
import { ExternalUrl } from "../../components/ExternalUrl.jsx";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { chunkLocation } from "../../lib/chunks.js";
import { formatTime } from "../../lib/format.js";
import { useResource } from "../../lib/useResource.js";
import { SaveToInvestigation } from "../investigations/SaveToInvestigation.jsx";

// Pages of chunks to load while looking for a focused one, and a safety cap.
const CHUNK_PAGE_SIZE = 50;
const MAX_CHUNK_PAGES = 40;

/** One document: its metadata, stored text and earlier revisions. */
export function DocumentDetailPage() {
  const { documentId } = useParams();
  const [params] = useSearchParams();
  const focusChunkId = params.get("chunk");
  const { tenantApi, can } = useOrganization();
  const navigate = useNavigate();
  const load = useCallback(async () => {
    const document = await tenantApi.get(`/documents/${documentId}`);
    const source = await tenantApi.get(`/sources/${document.source_id}`);
    return { document, source };
  }, [tenantApi, documentId]);
  const { data, error, loading } = useResource(load);

  async function remove() {
    await tenantApi.delete(`/documents/${documentId}`);
    navigate("/documents");
  }

  const document = data?.document;
  return (
    <>
      <PageHeading title={document ? document.title || "Untitled document" : "Document"}>
        <Link to="/documents">All documents</Link>
      </PageHeading>
      {loading && <Loading />}
      <ErrorMessage error={error} />
      {document && (
        <>
          <div className="page-actions">
            <SaveToInvestigation itemType="document" referenceId={document.id} />
          </div>
          {focusChunkId && (
            <FocusedChunk
              key={`${document.id}:${focusChunkId}`}
              documentId={document.id}
              chunkId={focusChunkId}
            />
          )}
          <section className="panel" aria-labelledby="document-details">
            <h2 id="document-details">Details</h2>
            <dl className="facts">
              <dt>Source</dt>
              <dd>
                <Link to={`/sources/${data.source.id}`}>{data.source.name}</Link>
              </dd>
              <dt>Published</dt>
              <dd>{formatTime(document.published_at)}</dd>
              <dt>Stored</dt>
              <dd>{formatTime(document.created_at)}</dd>
              <dt>Last changed</dt>
              <dd>{formatTime(document.updated_at)}</dd>
              <dt>Language</dt>
              <dd>{document.language ?? "-"}</dd>
              <dt>URL</dt>
              <dd>
                <ExternalUrl url={document.url} />
              </dd>
              <dt>External ID</dt>
              <dd>{document.external_id ?? "-"}</dd>
              <dt>Stored text</dt>
              <dd>
                {document.content === null ? "None" : `${document.content.length} characters`}
              </dd>
            </dl>
          </section>
          <section className="panel" aria-labelledby="document-text">
            <h2 id="document-text">Text</h2>
            {document.content ? (
              <div className="document-text">{document.content}</div>
            ) : (
              <p className="muted">This document has no stored text.</p>
            )}
          </section>
          <Revisions documentId={document.id} />
          {can.contribute && (
            <section className="panel" aria-labelledby="document-delete">
              <h2 id="document-delete">Delete</h2>
              <p className="muted">
                Deleting a document also deletes its chunks and everything extracted from it.
              </p>
              <ConfirmAction
                label="Delete document"
                question="Delete this document and everything extracted from it? This cannot be undone."
                confirmLabel="Yes, delete document"
                onConfirm={remove}
              />
            </section>
          )}
        </>
      )}
    </>
  );
}

function FocusedChunk({ documentId, chunkId }) {
  const { tenantApi } = useOrganization();
  const [state, setState] = useState({ loading: true, chunk: null, error: null, missing: false });
  const chunkRef = useRef(null);

  useEffect(() => {
    let active = true;
    (async () => {
      let offset = 0;
      for (let pageNumber = 0; pageNumber < MAX_CHUNK_PAGES; pageNumber += 1) {
        let page;
        try {
          page = await tenantApi.get(`/documents/${documentId}/chunks`, {
            query: { limit: CHUNK_PAGE_SIZE, offset },
          });
        } catch (error) {
          if (active) setState({ loading: false, chunk: null, error, missing: false });
          return;
        }
        if (!active) return;
        const found = page.items.find((item) => item.chunk_id === chunkId);
        if (found) {
          setState({ loading: false, chunk: found, error: null, missing: false });
          return;
        }
        offset += page.items.length;
        if (page.items.length === 0 || offset >= page.total) {
          setState({ loading: false, chunk: null, error: null, missing: true });
          return;
        }
      }
      if (active) setState({ loading: false, chunk: null, error: null, missing: true });
    })();
    return () => {
      active = false;
    };
  }, [tenantApi, documentId, chunkId]);

  useEffect(() => {
    if (state.chunk && chunkRef.current) {
      chunkRef.current.focus();
      chunkRef.current.scrollIntoView?.({ block: "center" });
    }
  }, [state.chunk]);

  return (
    <section className="panel" aria-labelledby="focused-chunk">
      <h2 id="focused-chunk">Focused evidence</h2>
      {state.loading && <Loading label="Finding the evidence..." />}
      <ErrorMessage error={state.error} />
      {state.missing && (
        <p className="muted" role="status">
          That piece of the document was not found. It may have changed since it was saved.
        </p>
      )}
      {state.chunk && (
        <div
          ref={chunkRef}
          tabIndex={-1}
          className="focused-evidence"
          aria-label={`Evidence at position ${state.chunk.position + 1}`}
        >
          <p className="muted">
            {chunkLocation(state.chunk.chunk_metadata) || "Highlighted passage"}
          </p>
          <blockquote>{state.chunk.text}</blockquote>
        </div>
      )}
    </section>
  );
}

function Revisions({ documentId }) {
  const { tenantApi } = useOrganization();
  const [version, setVersion] = useState(null);
  const load = useCallback(
    () => tenantApi.get(`/documents/${documentId}/revisions`),
    [tenantApi, documentId],
  );
  const { data, error, loading } = useResource(load);

  return (
    <section className="panel" aria-labelledby="document-revisions">
      <h2 id="document-revisions">Revisions</h2>
      <p className="muted">Earlier states of this document, kept when its content changed.</p>
      {loading && <Loading />}
      <ErrorMessage error={error} />
      {data && data.items.length === 0 && <p className="muted">No earlier revisions.</p>}
      {data && data.items.length > 0 && (
        <table>
          <thead>
            <tr>
              <th scope="col">Version</th>
              <th scope="col">Saved</th>
              <th scope="col">Title</th>
              <th scope="col">Language</th>
              <th scope="col">Text length</th>
              <th scope="col">Content hash</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((item) => (
              <tr key={item.version}>
                <td>
                  <button
                    type="button"
                    className="secondary"
                    aria-pressed={item.version === version}
                    onClick={() => setVersion(item.version)}
                  >
                    {`Version ${item.version}`}
                  </button>
                </td>
                <td>{formatTime(item.created_at)}</td>
                <td>{item.title ?? "-"}</td>
                <td>{item.language ?? "-"}</td>
                <td>{item.content_length ?? "-"}</td>
                <td>{item.content_hash ? item.content_hash.slice(0, 12) : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {version !== null && <Revision key={version} documentId={documentId} version={version} />}
    </section>
  );
}

function Revision({ documentId, version }) {
  const { tenantApi } = useOrganization();
  const load = useCallback(
    () => tenantApi.get(`/documents/${documentId}/revisions/${version}`),
    [tenantApi, documentId, version],
  );
  const { data, error, loading } = useResource(load);
  const metadata = data ? Object.entries(data.parser_metadata ?? {}) : [];
  return (
    <article aria-label={`Version ${version}`}>
      <h3>{`Version ${version}`}</h3>
      {loading && <Loading />}
      <ErrorMessage error={error} />
      {data && (
        <>
          <dl className="facts">
            <dt>Saved</dt>
            <dd>{formatTime(data.created_at)}</dd>
            <dt>Title</dt>
            <dd>{data.title ?? "-"}</dd>
            <dt>URL</dt>
            <dd>
              <ExternalUrl url={data.url} />
            </dd>
            {metadata.map(([key, value]) => (
              <div key={key} className="fact-pair">
                <dt>{`Parser: ${key}`}</dt>
                <dd>{typeof value === "object" ? JSON.stringify(value) : String(value)}</dd>
              </div>
            ))}
          </dl>
          {data.content ? (
            <div className="document-text">{data.content}</div>
          ) : (
            <p className="muted">This version had no stored text.</p>
          )}
        </>
      )}
    </article>
  );
}
