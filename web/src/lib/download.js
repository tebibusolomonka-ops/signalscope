/**
 * A download name from fixed words and a record ID, never from a title, so
 * it holds no path or odd characters: "signalscope-investigation-<id>.md".
 */
export function exportFileName(kind, id, extension) {
  const safeId = String(id).replace(/[^A-Za-z0-9-]/g, "");
  return `signalscope-${kind}-${safeId}.${extension}`;
}

/** Save text as a file in the browser. Nothing is written on the server. */
export function downloadText(fileName, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
