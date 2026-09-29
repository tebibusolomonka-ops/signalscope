/** How a source's scheduled ingestion is described. */
export function scheduleText(source) {
  if (source.ingestion_enabled) return `Every ${source.ingestion_interval_minutes} min`;
  if (source.ingestion_interval_minutes) return "Paused";
  return "Not scheduled";
}
