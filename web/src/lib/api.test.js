import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, createApiClient, parseError } from "./api.js";

const TOKEN = "test-token-value";

function jsonResponse(status, body) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function client(fetchImpl, token = TOKEN) {
  return createApiClient({ baseUrl: "/api", getToken: () => token, fetchImpl });
}

describe("parseError", () => {
  it("reads the SignalScope error shape", async () => {
    const error = await parseError(
      jsonResponse(409, {
        error: { code: "conflict", message: "Already a member.", details: [{ loc: ["x"] }] },
      }),
    );

    expect(error).toBeInstanceOf(ApiError);
    expect([error.status, error.code, error.message]).toEqual([409, "conflict", "Already a member."]);
    expect(error.details).toEqual([{ loc: ["x"] }]);
  });

  it("falls back when the body is not SignalScope JSON", async () => {
    const error = await parseError(new Response("oops", { status: 502, statusText: "Bad Gateway" }));

    expect([error.status, error.code, error.message]).toEqual([502, "error", "Bad Gateway"]);
  });
});

describe("createApiClient", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("sends JSON with the bearer token in a header, never in the URL", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(201, { id: "1" }));

    const result = await client(fetchImpl).post("/organizations", { name: "Harbour" }, {
      query: { limit: 10, status: undefined },
    });

    expect(result).toEqual({ id: "1" });
    const [url, options] = fetchImpl.mock.calls[0];
    expect(url).toBe("/api/organizations?limit=10");
    expect(url).not.toContain(TOKEN);
    expect(options.method).toBe("POST");
    expect(options.headers.Authorization).toBe(`Bearer ${TOKEN}`);
    expect(options.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(options.body)).toEqual({ name: "Harbour" });
  });

  it("leaves the header out without a token", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, []));

    await client(fetchImpl, null).get("/organizations");

    expect(fetchImpl.mock.calls[0][1].headers.Authorization).toBeUndefined();
  });

  it("returns null for 204 and throws ApiError for errors", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(
        jsonResponse(403, { error: { code: "forbidden", message: "Not allowed." } }),
      );
    const api = client(fetchImpl);

    expect(await api.delete("/auth/sessions/1")).toBeNull();
    await expect(api.get("/admin/users")).rejects.toMatchObject({
      status: 403,
      message: "Not allowed.",
    });
  });

  it("reports a network failure without details", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(client(fetchImpl).get("/auth/me")).rejects.toMatchObject({
      status: 0,
      code: "network_error",
    });
  });

  it("never logs the token", async () => {
    const spies = ["log", "info", "warn", "error", "debug"].map((name) =>
      vi.spyOn(console, name).mockImplementation(() => {}),
    );
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, {}))
      .mockResolvedValueOnce(jsonResponse(401, { error: { code: "x", message: "No." } }));
    const api = client(fetchImpl);

    await api.get("/auth/me");
    await expect(api.get("/auth/me")).rejects.toBeInstanceOf(ApiError);

    for (const spy of spies) {
      expect(spy).not.toHaveBeenCalled();
    }
  });
});
