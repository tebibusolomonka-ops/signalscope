/**
 * Where a chunk came from, from its chunk_metadata: "Page 3", a DOCX heading,
 * or the section kind and number. An empty string when nothing is known.
 */
export function chunkLocation(metadata) {
  if (!metadata) return "";
  const parts = [];
  if (metadata.page_number !== undefined) parts.push(`Page ${metadata.page_number}`);
  if (metadata.heading) parts.push(`Section: ${metadata.heading}`);
  if (parts.length === 0 && metadata.section_kind !== undefined) {
    parts.push(`${metadata.section_kind} ${Number(metadata.section_index ?? 0) + 1}`);
  }
  return parts.join(", ");
}
