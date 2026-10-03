import { Fragment } from "react";
import { Link } from "react-router";

import { chunkLocation } from "../lib/chunks.js";
import { documentHref } from "../lib/documentLink.js";

/**
 * One line that points at where a piece of evidence lives: the document, its
 * source, and the place in the document. Used by search, entity, claim and
 * event pages, event clusters and research, so references read the same way
 * and always link the document and the source.
 *
 * showDocument is false where a heading already links the document (search).
 * chunkId, when given, focuses that piece in the document. Without a
 * documentId the title is plain text, so there is never a broken link.
 */
export function EvidenceReference({
  documentId,
  documentTitle,
  sourceId,
  sourceName,
  metadata,
  chunkId = null,
  citationId = null,
  cited = false,
  showDocument = true,
}) {
  const location = chunkLocation(metadata);
  const parts = [];
  if (showDocument) {
    parts.push(
      documentId ? (
        <Link key="doc" to={documentHref(documentId, chunkId)}>
          {documentTitle || "Open document"}
        </Link>
      ) : (
        <span key="doc">{documentTitle || "Document unavailable"}</span>
      ),
    );
  }
  parts.push(
    sourceId ? (
      <Link key="source" to={`/sources/${sourceId}`}>
        {sourceName ?? "Source"}
      </Link>
    ) : (
      <span key="source">Source unknown</span>
    ),
  );
  if (location) parts.push(<span key="location">{location}</span>);
  if (cited)
    parts.push(
      <span key="cited" className="muted">
        cited
      </span>,
    );

  return (
    <span className="evidence-ref">
      {citationId && <strong>{`${citationId} `}</strong>}
      {parts.map((part, index) => (
        <Fragment key={part.key}>
          {index > 0 && " · "}
          {part}
        </Fragment>
      ))}
    </span>
  );
}
