import { describe, expect, it } from "vitest";

import { chunkLocation } from "./chunks.js";

describe("chunkLocation", () => {
  it.each([
    [{ page_number: 3, section_kind: "page", section_index: 2 }, "Page 3"],
    [{ heading: "Findings", section_kind: "block", section_index: 0 }, "Section: Findings"],
    [{ section_kind: "block", section_index: 1 }, "block 2"],
    [{}, ""],
    [null, ""],
  ])("%j", (metadata, expected) => {
    expect(chunkLocation(metadata)).toBe(expected);
  });
});
