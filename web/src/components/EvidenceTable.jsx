import { Link } from "react-router";

import { chunkLocation } from "../lib/chunks.js";

/**
 * Where an entity or claim was found: one row per mention or evidence row,
 * with the document and source it is in, the text span, and the model.
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
            <td>
              <Link to={`/documents/${row.document_id}`}>
                {row.document_title || "Untitled document"}
              </Link>
            </td>
            <td>
              {row.source_id ? (
                <Link to={`/sources/${row.source_id}`}>{row.source_name ?? "Source"}</Link>
              ) : (
                "-"
              )}
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
