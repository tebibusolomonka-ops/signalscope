import { Link } from "react-router";

import { chunkLocation } from "../lib/chunks.js";

/** A link to a document, showing its title, or a fallback when it has none. */
export function DocumentLink({ documentId, title }) {
  return <Link to={`/documents/${documentId}`}>{title || "Untitled document"}</Link>;
}

/** A link to a source, showing its name. */
export function SourceLink({ sourceId, name }) {
  return <Link to={`/sources/${sourceId}`}>{name}</Link>;
}

/**
 * An inline reference for one evidence row: its document and source, and where
 * in the document the chunk came from. Used wherever evidence is summarized.
 */
export function EvidenceReference({
  documentId,
  documentTitle,
  sourceId,
  sourceName,
  chunkMetadata,
}) {
  const location = chunkLocation(chunkMetadata);
  return (
    <span className="reference">
      <DocumentLink documentId={documentId} title={documentTitle} />
      {" · "}
      <SourceLink sourceId={sourceId} name={sourceName} />
      {location && ` · ${location}`}
    </span>
  );
}
