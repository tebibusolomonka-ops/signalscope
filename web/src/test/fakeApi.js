import { vi } from "vitest";

export const TOKEN = "fake-session-token";
export const ADMIN = {
  id: "u-admin",
  email: "admin@example.org",
  display_name: "Admin",
  is_active: true,
  is_system_admin: true,
};
/** A normal user; their role comes from GET /organizations. */
export const USER = {
  id: "u-user",
  email: "mel@example.org",
  display_name: "Mel",
  is_active: true,
  is_system_admin: false,
};

/**
 * A fetch stand-in. routes maps "METHOD /path" to an answer {status, body},
 * or to a function of the request that returns one. Unknown routes are 404.
 */
export function fakeApi(routes = {}) {
  const calls = [];
  const fetchImpl = vi.fn(async (url, options) => {
    const [path, query = ""] = url.replace(/^\/api/, "").split("?");
    // JSON bodies are parsed; a raw file body is kept as it is.
    const body = typeof options.body === "string" ? JSON.parse(options.body) : options.body;
    const request = {
      method: options.method,
      path,
      query: new URLSearchParams(query),
      body,
      options,
    };
    calls.push(request);
    const handler = routes[`${options.method} ${path}`];
    if (!handler) return answer(404, { error: { code: "not_found", message: "Not found." } });
    const result = typeof handler === "function" ? await handler(request) : handler;
    return answer(result.status ?? 200, result.body);
  });
  return { fetchImpl, calls };
}

function answer(status, body) {
  if (status === 204 || body === undefined) return new Response(null, { status });
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Routes for a signed in system admin. */
export function signedIn(user = ADMIN) {
  sessionStorage.setItem("signalscope.session", TOKEN);
  return {
    "GET /auth/me": { body: { user, session_id: "s-1", expires_at: "2026-10-08T00:00:00Z" } },
    "POST /auth/logout": { status: 204 },
  };
}
