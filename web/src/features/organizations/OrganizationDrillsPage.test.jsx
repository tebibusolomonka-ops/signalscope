import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ADMIN, signedIn, USER } from "../../test/fakeApi.js";
import { renderApp } from "../../test/renderApp.jsx";

function routes(user, role, drills = [], extraOrgs = []) {
  return {
    ...signedIn(user),
    "GET /organizations": {
      body: [
        { organization: { id: "org-1", name: "Harbour Watch" }, role },
        ...extraOrgs.map((organization) => ({ organization, role: "owner" })),
      ],
    },
    "GET /organizations/org-1/drills": { body: drills },
  };
}

const COMPLETED = {
  id: "drill-1",
  mode: "verification_only",
  status: "completed",
  started_at: "2026-10-05T10:00:00Z",
  finished_at: "2026-10-05T10:01:00Z",
  restore_id: null,
  safe_error: null,
};

describe("organization disaster recovery drills", () => {
  it("lists drills and runs a verification drill", async () => {
    const drills = [];
    const configured = routes(USER, "owner", drills);
    configured["POST /organizations/org-1/drills"] = ({ body }) => {
      expect(body).toEqual({ mode: "verification_only" });
      drills.unshift(COMPLETED);
      return { status: 201, body: COMPLETED };
    };
    renderApp({ path: "/organizations/org-1/drills", routes: configured });

    expect(await screen.findByText("No drills yet.")).toBeInTheDocument();
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Run verification drill" }));
    expect(await screen.findByText("verification_only")).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
  });

  it("lets a system admin run a restore test into a selected target", async () => {
    let posted;
    const configured = routes(ADMIN, null, [], [{ id: "org-2", name: "River Desk" }]);
    configured["POST /organizations/org-1/drills"] = ({ body }) => {
      posted = body;
      return { status: 201, body: { ...COMPLETED, mode: "restore_test", restore_id: "r-1" } };
    };
    renderApp({ path: "/organizations/org-1/drills", routes: configured });
    const user = userEvent.setup();

    await user.selectOptions(
      await screen.findByLabelText("Restore-test target organization"),
      "org-2",
    );
    await user.click(screen.getByRole("button", { name: "Run restore test" }));

    expect(posted).toEqual({ mode: "restore_test", target_organization_id: "org-2" });
  });

  it("hides the restore test from a normal organization admin", async () => {
    renderApp({ path: "/organizations/org-1/drills", routes: routes(USER, "admin") });

    expect(
      await screen.findByRole("button", { name: "Run verification drill" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText("Restore-test target organization"),
    ).not.toBeInTheDocument();
  });

  it("hides actions from a viewer", async () => {
    renderApp({ path: "/organizations/org-1/drills", routes: routes(USER, "viewer") });

    expect(await screen.findByText("No drills yet.")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Run verification drill" }),
    ).not.toBeInTheDocument();
  });
});
