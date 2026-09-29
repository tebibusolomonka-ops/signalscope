import { vi } from "vitest";

/**
 * Catch browser downloads: every file saved through an object URL and a
 * link click is recorded as {name, blob}. Call the returned restore() after.
 */
export function captureDownloads() {
  const files = [];
  const original = { create: URL.createObjectURL, revoke: URL.revokeObjectURL };
  URL.createObjectURL = vi.fn((blob) => {
    files.push({ blob, name: null });
    return `blob:download-${files.length}`;
  });
  URL.revokeObjectURL = vi.fn();
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function () {
    files.at(-1).name = this.download;
  });
  function restore() {
    URL.createObjectURL = original.create;
    URL.revokeObjectURL = original.revoke;
    click.mockRestore();
  }
  return { files, restore };
}
