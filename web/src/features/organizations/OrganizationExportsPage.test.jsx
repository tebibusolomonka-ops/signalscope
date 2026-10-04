import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { captureDownloads } from "../../test/downloads.js";
import { signedIn, USER } from "../../test/fakeApi.js";
import { renderApp } from "../../test/renderApp.jsx";

const EXPORT = {
  id: "export-1",
  organization_id: "org-1",
  requested_by_user_id: "user-1",
  status: "completed",
  format_version: "1",
  created_at: "2026-10-02T12:00:00Z",
  started_at: "2026-10-02T12:00:00Z",
  finished_at: "2026-10-02T12:01:00Z",
  expires_at: null,
  size_bytes: 1536,
  sha256: "a".repeat(64),
  safe_error: null,
};
const ASSETS = { asset_count: 0, asset_bytes: 0, max_assets: 10000, max_bytes: 500000000 };

let downloads;
afterEach(() => downloads?.restore());

describe("organization exports", () => {
  it("lists, creates and downloads tenant exports", async () => {
    downloads = captureDownloads();
    const exports = [EXPORT];
    const { calls } = renderApp({
      path: "/organizations/org-1/exports",
      routes: {
        ...signedIn(USER),
        "GET /organizations": {
          body: [{ organization: { id: "org-1", name: "Harbour Watch" }, role: "owner" }],
        },
        "GET /organizations/org-1/exports": () => ({ body: exports }),
        "GET /organizations/org-1/exports/assets": {
          body: { asset_count: 2, asset_bytes: 1536, max_assets: 10000, max_bytes: 500000000 },
        },
        "POST /organizations/org-1/exports": () => {
          exports.unshift({ ...EXPORT, id: "export-2", status: "running" });
          return { status: 201, body: exports[0] };
        },
        "GET /organizations/org-1/exports/export-1/download": {
          body: new Blob(["zip-data"], { type: "application/zip" }),
          type: "blob",
        },
        "POST /organizations/org-1/exports/export-1/verify": {
          body: { valid: true, checked_files: 3, checked_records: 8, problems: [] },
        },
      },
    });

    expect(await screen.findByText("1.5 KB")).toBeInTheDocument();
    expect(screen.getByText(/Export assets: 2 \(1.5 KB\)/)).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
    expect(screen.getByText("1", { selector: "td" })).toBeInTheDocument();
    expect(screen.queryByText("organization-exports/private.zip")).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Create export" }));
    await waitFor(() => expect(screen.getByText("running")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(downloads.files).toHaveLength(1));

    expect(downloads.files[0].name).toBe("signalscope-organization-org-1.zip");
    expect(calls.some((call) => call.method === "POST")).toBe(true);
    expect(calls.at(-1).path).toBe("/organizations/org-1/exports/export-1/download");

    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByRole("heading", { name: "Valid" })).toBeInTheDocument();
    expect(screen.getByText("Checked files: 3")).toBeInTheDocument();
    expect(screen.getByText("Checked records: 8")).toBeInTheDocument();
  });

  it("shows permission failures", async () => {
    renderApp({
      path: "/organizations/org-1/exports",
      routes: {
        ...signedIn(USER),
        "GET /organizations": {
          body: [{ organization: { id: "org-1", name: "Harbour Watch" }, role: "member" }],
        },
        "GET /organizations/org-1/exports": {
          status: 403,
          body: { error: { code: "forbidden", message: "Only owners and admins may export." } },
        },
        "GET /organizations/org-1/exports/assets": { body: ASSETS },
      },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("Only owners and admins may export.");
  });

  it("shows verification problems", async () => {
    renderApp({
      path: "/organizations/org-1/exports",
      routes: {
        ...signedIn(USER),
        "GET /organizations": {
          body: [{ organization: { id: "org-1", name: "Harbour Watch" }, role: "admin" }],
        },
        "GET /organizations/org-1/exports": { body: [EXPORT] },
        "GET /organizations/org-1/exports/assets": { body: ASSETS },
        "POST /organizations/org-1/exports/export-1/verify": {
          body: {
            valid: false,
            checked_files: 2,
            checked_records: 4,
            problems: ["Archive member checksum does not match: documents.jsonl"],
          },
        },
      },
    });

    await userEvent.setup().click(await screen.findByRole("button", { name: "Verify" }));

    expect(
      await screen.findByRole("heading", { name: "Verification problems" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/checksum does not match/)).toBeInTheDocument();
  });

  it("shows verification loading state", async () => {
    let finish;
    renderApp({
      path: "/organizations/org-1/exports",
      routes: {
        ...signedIn(USER),
        "GET /organizations": {
          body: [{ organization: { id: "org-1", name: "Harbour Watch" }, role: "owner" }],
        },
        "GET /organizations/org-1/exports": { body: [EXPORT] },
        "GET /organizations/org-1/exports/assets": { body: ASSETS },
        "POST /organizations/org-1/exports/export-1/verify": () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      },
    });

    await userEvent.setup().click(await screen.findByRole("button", { name: "Verify" }));

    expect(screen.getByRole("button", { name: "Verifying..." })).toBeDisabled();
    finish({ body: { valid: true, checked_files: 1, checked_records: 1, problems: [] } });
    expect(await screen.findByRole("heading", { name: "Valid" })).toBeInTheDocument();
  });

  it("hides verification from roles without export permission", async () => {
    renderApp({
      path: "/organizations/org-1/exports",
      routes: {
        ...signedIn(USER),
        "GET /organizations": {
          body: [{ organization: { id: "org-1", name: "Harbour Watch" }, role: "member" }],
        },
        "GET /organizations/org-1/exports": { body: [EXPORT] },
        "GET /organizations/org-1/exports/assets": { body: ASSETS },
      },
    });

    expect(await screen.findByText("1.5 KB")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Verify" })).not.toBeInTheDocument();
  });

  it("clears verification when the active organization changes", async () => {
    renderApp({
      path: "/organizations/org-1/exports",
      routes: {
        ...signedIn(USER),
        "GET /organizations": {
          body: [
            { organization: { id: "org-1", name: "Harbour Watch" }, role: "owner" },
            { organization: { id: "org-2", name: "City Desk" }, role: "owner" },
          ],
        },
        "GET /organizations/org-1/exports": { body: [EXPORT] },
        "GET /organizations/org-1/exports/assets": { body: ASSETS },
        "POST /organizations/org-1/exports/export-1/verify": {
          body: { valid: true, checked_files: 1, checked_records: 1, problems: [] },
        },
      },
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Verify" }));
    expect(await screen.findByRole("heading", { name: "Valid" })).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Active organization"), "org-2");

    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Valid" })).not.toBeInTheDocument(),
    );
  });
});
