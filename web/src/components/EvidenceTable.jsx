import { chunkLocation } from "../lib/chunks.js";
import { DocumentLink, SourceLink } from "./references.jsx";

/**
 * Where an entity or claim was found: one row per mention or evidence row,
 * with the text span, its place and the model that found it.
 */
export function EvidenceTable({ rows, label }) {
  return (
    <table aria-label={label}>
      <thead>
        <tr>
          <th scope="col">Document</th>
          <th scope="col">Source</th>
          <th scope="col">Text</th>
          <th scope="col">Location</th>
          <th scope="col">Characters</th>
          <th scope="col">Confidence</th>
          <th scope="col">Found by</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.id}>
            <td className="wrap">
              <DocumentLink documentId={row.document_id} title={row.document_title} />
            </td>
            <td>
              <SourceLink sourceId={row.source_id} name={row.source_name} />
            </td>
            <td className="wrap">{row.surface_text}</td>
            <td>{chunkLocation(row.chunk_metadata) || "-"}</td>
            <td>{`${row.start_char} to ${row.end_char}`}</td>
            <td>{row.confidence === null ? "-" : Number(row.confidence).toFixed(2)}</td>
            <td className="wrap">{`${row.provider} / ${row.model}`}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
