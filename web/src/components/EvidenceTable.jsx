import { EvidenceReference } from "./EvidenceReference.jsx";

/**
 * Where an entity or claim was found: one row per mention or evidence row,
 * with the document and source it is in, the text span, and the model.
 */
export function EvidenceTable({ rows, label }) {
  return (
    <table aria-label={label}>
      <thead>
        <tr>
          <th scope="col">Where</th>
          <th scope="col">Text</th>
          <th scope="col">Characters</th>
          <th scope="col">Confidence</th>
          <th scope="col">Found by</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.id}>
            <td>
              <EvidenceReference
                documentId={row.document_id}
                documentTitle={row.document_title}
                chunkId={row.chunk_id}
                sourceId={row.source_id}
                sourceName={row.source_name}
                metadata={row.chunk_metadata}
              />
            </td>
            <td className="wrap">{row.surface_text}</td>
            <td>{`${row.start_char} to ${row.end_char}`}</td>
            <td>{row.confidence === null ? "-" : Number(row.confidence).toFixed(2)}</td>
            <td className="wrap">{`${row.provider} / ${row.model}`}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
