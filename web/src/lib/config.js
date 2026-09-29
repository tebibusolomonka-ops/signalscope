const DEFAULT_API_URL = "/api";

/** The API base URL from VITE_SIGNALSCOPE_API_URL, without a trailing slash. */
export function apiBaseUrl(env = import.meta.env) {
  const value = (env.VITE_SIGNALSCOPE_API_URL ?? "").trim();
  return (value || DEFAULT_API_URL).replace(/\/+$/, "");
}
