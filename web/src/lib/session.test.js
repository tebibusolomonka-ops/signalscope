import { afterEach, describe, expect, it, vi } from "vitest";

import { clearToken, readToken, saveToken } from "./session.js";

describe("session token", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    clearToken();
  });

  it("uses sessionStorage and never localStorage", () => {
    saveToken("abc");

    expect(sessionStorage.getItem("signalscope.session")).toBe("abc");
    expect(localStorage.length).toBe(0);
    expect(readToken()).toBe("abc");
    clearToken();
    expect(readToken()).toBeNull();
  });

  it("keeps the token in memory when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    saveToken("abc");

    expect(readToken()).toBe("abc");
  });
});
