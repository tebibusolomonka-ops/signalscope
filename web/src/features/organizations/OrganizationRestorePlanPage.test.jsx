import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ADMIN, signedIn, USER } from "../../test/fakeApi.js";
import { renderApp } from "../../test/renderApp.jsx";

const PLAN = {
  archive: { format_version: "1", checked_files: 4, checked_records: 12 },
  inventory: {
    counts: { sources: 2, documents: 3 },
    asset_count: 1,
    referenced_user_ids: ["old-user"],
  },
  conflicts: ["Target organization must be empty for restore."],
  warnings: ["Assets require verified binary content before restore."],
  unresolved_user_ids: ["old-user"],
};

describe("organization restore planning", () => {
  it("uploads an export and shows the dry-run plan", async () => {
    const { calls } = renderApp({
      path: "/organizations/org-1/restore-plan",
      routes: {
        ...signedIn(ADMIN),
        "GET /organizations": { body: [] },
        "POST /organizations/org-1/restore-plan": { body: PLAN },
      },
    });
    const user = userEvent.setup();
    const file = new File(["archive"], "organization.zip", { type: "application/zip" });

    await user.upload(await screen.findByLabelText("Organization export ZIP"), file);
    await user.click(screen.getByRole("button", { name: "Plan restore" }));

    expect(await screen.findByRole("region", { name: "Restore plan" })).toBeInTheDocument();
    expect(screen.getByText("Checked records: 12")).toBeInTheDocument();
    expect(screen.getByText("Target organization must be empty for restore.")).toBeInTheDocument();
    expect(screen.getByText("old-user")).toBeInTheDocument();
    expect(calls.at(-1).body).toBe(file);
    expect(calls.at(-1).options.headers["Content-Type"]).toBe("application/zip");
  });

  it("shows planning failures", async () => {
    renderApp({
      path: "/organizations/org-1/restore-plan",
      routes: {
        ...signedIn(ADMIN),
        "GET /organizations": { body: [] },
        "POST /organizations/org-1/restore-plan": {
          status: 422,
          body: { error: { code: "invalid_archive", message: "Archive verification failed." } },
        },
      },
    });
    const user = userEvent.setup();

    await user.upload(
      await screen.findByLabelText("Organization export ZIP"),
      new File(["bad"], "bad.zip", { type: "application/zip" }),
    );
    await user.click(screen.getByRole("button", { name: "Plan restore" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Archive verification failed.");
  });

  it("does not expose the workspace to normal users", async () => {
    renderApp({
      path: "/organizations/org-1/restore-plan",
      routes: { ...signedIn(USER), "GET /organizations": { body: [] } },
    });

    expect(await screen.findByText("You do not have permission to plan restores.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Organization export ZIP")).not.toBeInTheDocument();
  });

  it("shows a busy state while the archive is checked", async () => {
    let finish;
    renderApp({
      path: "/organizations/org-1/restore-plan",
      routes: {
        ...signedIn(ADMIN),
        "GET /organizations": { body: [] },
        "POST /organizations/org-1/restore-plan": () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      },
    });
    const user = userEvent.setup();

    await user.upload(
      await screen.findByLabelText("Organization export ZIP"),
      new File(["archive"], "organization.zip", { type: "application/zip" }),
    );
    await user.click(screen.getByRole("button", { name: "Plan restore" }));

    expect(screen.getByRole("button", { name: "Planning..." })).toBeDisabled();
    finish({ body: PLAN });
    await waitFor(() => expect(screen.getByText("Format version: 1")).toBeInTheDocument());
  });
});
