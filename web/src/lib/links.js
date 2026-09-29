/** An http or https URL from content, or null, so no other scheme becomes a link. */
export function safeHref(url) {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null;
  }
}
