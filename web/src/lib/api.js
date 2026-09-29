/**
 * A small fetch wrapper for the SignalScope API.
 *
 * It sends JSON, adds the bearer token when there is one, and turns error
 * answers into ApiError. It never logs, and never puts the token in a URL.
 */

export class ApiError extends Error {
  constructor(status, code, message, details = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

const FALLBACK_MESSAGE = "The request failed.";

/** Read SignalScope's {"error": {"code", "message", "details"}} answer. */
export async function parseError(response) {
  let body;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  const error = body && typeof body === "object" ? body.error : null;
  if (error && typeof error.message === "string") {
    return new ApiError(
      response.status,
      error.code ?? "error",
      error.message,
      Array.isArray(error.details) ? error.details : [],
    );
  }
  return new ApiError(response.status, "error", response.statusText || FALLBACK_MESSAGE);
}

function withQuery(path, query) {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") params.append(key, String(value));
  }
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

export function createApiClient({ baseUrl, getToken = () => null, fetchImpl }) {
  const send = fetchImpl ?? ((...args) => fetch(...args));

  async function request(method, path, { body, query } = {}) {
    const headers = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    let response;
    try {
      response = await send(`${baseUrl}${withQuery(path, query)}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw new ApiError(0, "network_error", "The API could not be reached.");
    }
    if (!response.ok) throw await parseError(response);
    if (response.status === 204) return null;
    return response.json();
  }

  return {
    request,
    get: (path, options) => request("GET", path, options),
    post: (path, body, options) => request("POST", path, { ...options, body }),
    patch: (path, body, options) => request("PATCH", path, { ...options, body }),
    delete: (path, options) => request("DELETE", path, options),
  };
}
