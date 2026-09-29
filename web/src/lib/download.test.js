import { describe, expect, it } from "vitest";

import { exportFileName } from "./download.js";

describe("exportFileName", () => {
  it("uses fixed words and the ID only", () => {
    expect(exportFileName("investigation", "5f1c-22ab", "md")).toBe(
      "signalscope-investigation-5f1c-22ab.md",
    );
  });

  it("drops anything that could form a path", () => {
    expect(exportFileName("research-session", "../../etc/passwd x", "json")).toBe(
      "signalscope-research-session-etcpasswdx.json",
    );
  });
});
