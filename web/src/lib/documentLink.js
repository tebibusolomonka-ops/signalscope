/**
 * A link to a document, optionally focused on one chunk. The chunk ID is not
 * secret, so it may be a query parameter; chunk text and tokens never are.
 */
export function documentHref(documentId, chunkId = null) {
  return chunkId ? `/documents/${documentId}?chunk=${chunkId}` : `/documents/${documentId}`;
}
