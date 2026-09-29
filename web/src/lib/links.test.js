import { describe, expect, it } from "vitest";

import { safeHref } from "./links.js";

describe("safeHref", () => {
  it.each([
    ["https://example.org/a", "https://example.org/a"],
    ["http://example.org/", "http://example.org/"],
    ["javascript:alert(1)", null],
    ["data:text/html,x", null],
    ["not a url", null],
    [null, null],
  ])("%s", (url, expected) => {
    expect(safeHref(url)).toBe(expected);
  });
});
