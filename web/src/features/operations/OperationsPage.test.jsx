import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { held, operationsOverview } from "../../test/content.js";
import { USER, signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

function routes(extra = {}, role = "owner", user) {
  return {
    ...signedIn(user),
    ...organizations([HARBOUR, RIVER], role),
    "GET /operations/overview": {
      body: operationsOverview({
        embedding: {
          pending_count: 3,
          running_count: 1,
          failed_count: 2,
          oldest_pending_at: "2026-09-10T08:00:00Z",
          oldest_failed_at: "2026-09-11T09:30:00Z",
        },
      }),
    },
    ...extra,
  };
}

function overviewCalls(calls) {
  return calls.filter((call) => call.path === "/operations/overview");
}

describe("operations workspace", () => {
  it("shows one row per queue with its counts", async () => {
    const { calls } = renderApp({ path: "/operations", routes: routes() });

    const embedding = (await screen.findByRole("rowheader", { name: "Embedding" })).closest("tr");
    const section = screen.getByRole("region", { name: "Queues" });
    expect(
      within(embedding)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual(["3", "1", "2", "2026-09-10 08:00 UTC", "2026-09-11 09:30 UTC"]);
    const ingestion = within(section).getByRole("rowheader", { name: "Ingestion" }).closest("tr");
    expect(
      within(ingestion)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual(["0", "0", "0", "-", "-"]);
    expect(within(section).getAllByRole("rowheader")).toHaveLength(6);
    expect(overviewCalls(calls)[0].query.get("organization_id")).toBe("org-a");
  });

  it("reloads on refresh", async () => {
    const { calls } = renderApp({ path: "/operations", routes: routes() });
    const user = userEvent.setup();

    await screen.findByRole("region", { name: "Queues" });
    await user.click(screen.getByRole("button", { name: "Refresh" }));

    await waitFor(() => expect(overviewCalls(calls).length).toBeGreaterThan(1));
  });

  it("shows the API error", async () => {
    renderApp({
      path: "/operations",
      routes: routes({
        "GET /operations/overview": {
          status: 503,
          body: { error: { code: "service_unavailable", message: "Database is not configured." } },
        },
      }),
    });
    const queues = await screen.findByRole("region", { name: "Queues" });
    expect(await within(queues).findByRole("alert")).toHaveTextContent("Database is not configured.");
  });

  it("tells members they cannot see operations", async () => {
    const { calls } = renderApp({ path: "/operations", routes: routes({}, "member", USER) });

    expect(
      await screen.findByText("Only organization owners and admins can see operations."),
    ).toBeInTheDocument();
    expect(overviewCalls(calls)).toHaveLength(0);
  });

  it("drops the old organization's counts when switching", async () => {
    const river = held();
    renderApp({
      path: "/operations",
      routes: routes({
        "GET /operations/overview": async ({ query }) => {
          if (query.get("organization_id") === "org-b") {
            await river.ready;
            return { body: operationsOverview({ ingestion: { pending_count: 99 } }) };
          }
          return { body: operationsOverview({ embedding: { pending_count: 3 } }) };
        },
      }),
    });
    const user = userEvent.setup();

    const row = (await screen.findByRole("rowheader", { name: "Embedding" })).closest("tr");
    expect(row).toHaveTextContent("3");
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    // While B loads, A's counts are gone; A's answer never fills B's page.
    await waitFor(() =>
      expect(screen.queryByRole("rowheader", { name: "Embedding" })).not.toBeInTheDocument(),
    );
    river.release();
    expect(await screen.findByRole("rowheader", { name: "Ingestion" })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "Ingestion" }).closest("tr")).toHaveTextContent(
      "99",
    );
  });
});
