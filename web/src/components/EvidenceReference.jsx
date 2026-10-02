import { Fragment } from "react";
import { Link } from "react-router";

import { chunkLocation } from "../lib/chunks.js";

/**
 * One line that points at where a piece of evidence lives: the document, its
 * source, and the place in the document. Used by search, entity, claim and
 * event pages, event clusters and research, so references read the same way
 * and always link the document and the source.
 *
 * showDocument is false where a heading already links the document (search).
 */
export function EvidenceReference({
  documentId,
  documentTitle,
  sourceId,
  sourceName,
  metadata,
  citationId = null,
  cited = false,
  showDocument = true,
}) {
  const location = chunkLocation(metadata);
  const parts = [];
  if (showDocument) {
    parts.push(
      <Link key="doc" to={`/documents/${documentId}`}>
        {documentTitle || "Open document"}
      </Link>,
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
