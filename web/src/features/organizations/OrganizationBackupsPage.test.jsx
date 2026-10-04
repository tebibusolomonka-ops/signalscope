import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { signedIn, USER } from "../../test/fakeApi.js";
import { renderApp } from "../../test/renderApp.jsx";

const POLICY = {
  organization_id: "org-1",
  enabled: false,
  frequency: "daily",
  retention_count: 7,
  include_assets: false,
  last_run_at: null,
  next_run_at: null,
  updated_at: null,
};

function routes(role = "owner", backups = []) {
  return {
    ...signedIn(USER),
    "GET /organizations": {
      body: [{ organization: { id: "org-1", name: "Harbour Watch" }, role }],
    },
    "GET /organizations/org-1/backup-policy": { body: POLICY },
    "GET /organizations/org-1/backups": { body: backups },
  };
}

describe("organization backups", () => {
  it("shows a disabled policy and saves enabled weekly backups", async () => {
    let saved;
    const configured = routes();
    configured["PUT /organizations/org-1/backup-policy"] = ({ body }) => {
      saved = body;
      return { body: { ...POLICY, ...body, next_run_at: "2026-10-05T12:00:00Z" } };
    };
    const { calls } = renderApp({ path: "/organizations/org-1/backups", routes: configured });
    const user = userEvent.setup();

    expect(await screen.findByLabelText("Scheduled backups enabled")).not.toBeChecked();
    await user.click(screen.getByLabelText("Scheduled backups enabled"));
    await user.selectOptions(screen.getByLabelText("Frequency"), "weekly");
    await user.clear(screen.getByLabelText("Backups to keep"));
    await user.type(screen.getByLabelText("Backups to keep"), "3");
    await user.click(screen.getByLabelText("Include binary assets"));
    await user.click(screen.getByRole("button", { name: "Save backup policy" }));

    await waitFor(() => expect(saved).toEqual({
      enabled: true,
      frequency: "weekly",
      retention_count: 3,
      include_assets: true,
    }));
    expect(calls.some((call) => call.method === "PUT")).toBe(true);
  });

  it("runs a backup and distinguishes verified and failed results", async () => {
    const backups = [
      {
        id: "failed-1",
        status: "failed",
        created_at: "2026-10-04T10:00:00Z",
        size_bytes: null,
        safe_error: "Backup export verification failed.",
      },
    ];
    const configured = routes("admin", backups);
    configured["POST /organizations/org-1/backups/run"] = () => {
      backups.unshift({
        id: "backup-1",
        status: "completed",
        created_at: "2026-10-04T12:00:00Z",
        size_bytes: 2048,
        safe_error: null,
      });
      return { status: 201, body: backups[0] };
    };
    renderApp({ path: "/organizations/org-1/backups", routes: configured });

    expect(await screen.findByText("failed")).toBeInTheDocument();
    expect(screen.queryByText("Verified")).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Run backup now" }));
    expect(await screen.findByText("Verified")).toBeInTheDocument();
    expect(screen.getByText("2.0 KB")).toBeInTheDocument();
  });

  it("does not show actions to roles without permission", async () => {
    renderApp({ path: "/organizations/org-1/backups", routes: routes("viewer") });

    expect(await screen.findByLabelText("Scheduled backups enabled")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save backup policy" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run backup now" })).not.toBeInTheDocument();
  });
});
