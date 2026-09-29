import { safeHref } from "../lib/links.js";

/** A content URL as a link that opens outside the app, or as text when it is not http(s). */
export function ExternalUrl({ url }) {
  if (!url) return "-";
  const href = safeHref(url);
  if (!href) return url;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {url}
    </a>
  );
}
