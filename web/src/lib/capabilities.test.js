import { describe, expect, it } from "vitest";

import { contentCapabilities } from "./capabilities.js";

describe("contentCapabilities", () => {
  it.each([
    ["viewer", false, { read: true, contribute: false, manage: false }],
    ["member", false, { read: true, contribute: true, manage: false }],
    ["admin", false, { read: true, contribute: true, manage: true }],
    ["owner", false, { read: true, contribute: true, manage: true }],
    ["viewer", true, { read: true, contribute: true, manage: true }],
    [undefined, false, { read: false, contribute: false, manage: false }],
  ])("%s (system admin %s)", (role, isSystemAdmin, expected) => {
    expect(contentCapabilities(role, isSystemAdmin)).toEqual(expected);
  });
});
