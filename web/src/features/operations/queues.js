/** Human labels for the operations queues, in the order the API returns them. */
export const QUEUE_LABELS = {
  ingestion: "Ingestion",
  processing: "Processing",
  embedding: "Embedding",
  entity_extraction: "Entity extraction",
  event_extraction: "Event extraction",
  claim_extraction: "Claim extraction",
};

export function queueLabel(queue) {
  return QUEUE_LABELS[queue] ?? queue;
}
