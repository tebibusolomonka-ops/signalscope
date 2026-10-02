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
        "POST /organizations/org-1/exports": () => {
          exports.unshift({ ...EXPORT, id: "export-2", status: "running" });
          return { status: 201, body: exports[0] };
        },
        "GET /organizations/org-1/exports/export-1/download": {
          body: new Blob(["zip-data"], { type: "application/zip" }),
          type: "blob",
        },
      },
    });

    expect(await screen.findByText("1.5 KB")).toBeInTheDocument();
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
      },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("Only owners and admins may export.");
  });
});
