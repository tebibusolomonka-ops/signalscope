import { describe, expect, it } from "vitest";

import { documentHref } from "./documentLink.js";

describe("documentHref", () => {
  it("links the document alone when there is no chunk", () => {
    expect(documentHref("d-1")).toBe("/documents/d-1");
    expect(documentHref("d-1", null)).toBe("/documents/d-1");
  });

  it("focuses a chunk when one is given", () => {
    expect(documentHref("d-1", "c-2")).toBe("/documents/d-1?chunk=c-2");
  });
});
