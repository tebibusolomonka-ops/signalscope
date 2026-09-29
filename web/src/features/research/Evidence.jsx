import { Fragment } from "react";
import { Link } from "react-router";

import { chunkLocation } from "../../lib/chunks.js";
import { evidenceElementId } from "./evidenceFocus.js";

const MARKER = /\[(E\d+)\]/g;

/**
 * An answer with its [E1] markers turned into buttons that show the cited
 * evidence. The answer is the model's text; the evidence is the source.
 */
export function AnswerText({ text, onCite }) {
  const parts = text.split(MARKER);
  return (
    <p className="answer-text">
      {parts.map((part, index) =>
        index % 2 === 1 ? (
          <button
            key={index}
            type="button"
            className="cite"
            aria-label={`Show evidence ${part}`}
            onClick={() => onCite(part)}
          >
            {`[${part}]`}
          </button>
        ) : (
          <Fragment key={index}>{part}</Fragment>
        ),
      )}
    </p>
  );
}

/** One numbered piece of evidence: an excerpt of a document chunk. */
export function EvidenceCard({ item, scope, sourceName, cited = false }) {
  const location = chunkLocation(item.chunk_metadata);
  return (
    <li
      id={evidenceElementId(scope, item.evidence_id)}
      tabIndex={-1}
      className={cited ? "evidence cited" : "evidence"}
      aria-label={`Evidence ${item.evidence_id}`}
    >
      <p className="evidence-head">
        <strong>{item.evidence_id}</strong>{" "}
        <Link to={`/documents/${item.document_id}`}>{item.title || "Untitled document"}</Link>
        {" · "}
        <Link to={`/sources/${item.source_id}`}>{sourceName ?? "Source"}</Link>
        {location && ` · ${location}`}
        {cited && <span className="muted"> · cited</span>}
      </p>
      <blockquote>{item.excerpt}</blockquote>
    </li>
  );
}
