import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { USER, signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

function overview(overrides = {}) {
  return {
    organization: { id: "org-a", name: "Harbour Watch", slug: "harbour" },
    queues: [
      {
        queue: "ingestion",
        pending_count: 2,
        running_count: 1,
        failed_count: 3,
        oldest_pending_at: "2026-09-20T08:00:00Z",
        oldest_failed_at: "2026-09-21T08:00:00Z",
      },
      {
        queue: "claim_extraction",
        pending_count: 0,
        running_count: 0,
        failed_count: 0,
        oldest_pending_at: null,
        oldest_failed_at: null,
      },
    ],
    ...overrides,
  };
}

function routes(extra = {}, role = "owner", user) {
  return {
    ...signedIn(user),
    ...organizations([HARBOUR, RIVER], role),
    "GET /operations/overview": { body: overview() },
    ...extra,
  };
}

describe("operations page", () => {
  it("shows queue counts and sends the organization", async () => {
    const { calls } = renderApp({ path: "/operations", routes: routes() });

    const section = await screen.findByRole("region", { name: "Queues" });
    const rows = within(section).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("Ingestion");
    expect(rows[0]).toHaveTextContent("2026-09-20 08:00 UTC");
    expect(rows[1]).toHaveTextContent("Claim extraction");
    // A queue with no failures shows a dash for the oldest failed time.
    expect(rows[1]).toHaveTextContent("-");
    const overviewCalls = calls.filter((call) => call.path === "/operations/overview");
    expect(overviewCalls).toHaveLength(1);
    expect(overviewCalls[0].query.get("organization_id")).toBe("org-a");
  });

  it("refreshes on demand", async () => {
    const { calls } = renderApp({ path: "/operations", routes: routes() });
    const user = userEvent.setup();

    const section = await screen.findByRole("region", { name: "Queues" });
    await user.click(within(section).getByRole("button", { name: "Refresh" }));

    await waitFor(() =>
      expect(calls.filter((call) => call.path === "/operations/overview").length).toBe(2),
    );
  });

  it("is not shown to members", async () => {
    renderApp({ path: "/operations", routes: routes({}, "member", USER) });

    expect(
      await screen.findByText("Operations are for organization owners and admins."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Queues" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Operations" })).not.toBeInTheDocument();
  });

  it("links to operations for managers", async () => {
    renderApp({ path: "/dashboard", routes: routes({ "GET /dashboard/overview": { body: {} } }) });

    expect(await screen.findByRole("link", { name: "Operations" })).toBeInTheDocument();
  });
});
