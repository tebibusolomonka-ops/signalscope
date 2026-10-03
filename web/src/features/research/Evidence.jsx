import { Fragment } from "react";

import { EvidenceReference } from "../../components/EvidenceReference.jsx";
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
  return (
    <li
      id={evidenceElementId(scope, item.evidence_id)}
      tabIndex={-1}
      className={cited ? "evidence cited" : "evidence"}
      aria-label={`Evidence ${item.evidence_id}`}
    >
      <p className="evidence-head">
        <EvidenceReference
          citationId={item.evidence_id}
          documentId={item.document_id}
          documentTitle={item.title}
          chunkId={item.chunk_id}
          sourceId={item.source_id}
          sourceName={sourceName}
          metadata={item.chunk_metadata}
          cited={cited}
        />
      </p>
      <blockquote>{item.excerpt}</blockquote>
    </li>
  );
}
