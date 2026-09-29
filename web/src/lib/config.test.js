import { describe, expect, it } from "vitest";

import { apiBaseUrl } from "./config.js";

describe("apiBaseUrl", () => {
  it("defaults to the proxied /api path", () => {
    expect(apiBaseUrl({})).toBe("/api");
    expect(apiBaseUrl({ VITE_SIGNALSCOPE_API_URL: "  " })).toBe("/api");
  });

  it("uses the configured URL without a trailing slash", () => {
    expect(apiBaseUrl({ VITE_SIGNALSCOPE_API_URL: "https://api.example.org/" })).toBe(
      "https://api.example.org",
    );
    expect(apiBaseUrl({ VITE_SIGNALSCOPE_API_URL: "/backend" })).toBe("/backend");
  });
});
