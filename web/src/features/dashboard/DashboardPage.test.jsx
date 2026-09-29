import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DASHBOARD_ROUTES } from "../../test/dashboardRoutes.js";
import { ADMIN, signedIn } from "../../test/fakeApi.js";
import { renderApp } from "../../test/renderApp.jsx";

const HARBOUR = { id: "org-a", name: "Harbour Watch", slug: "harbour" };
const RIVER = { id: "org-b", name: "River Desk", slug: "river" };

function organizations(...items) {
  return { body: items.map((organization) => ({ organization, role: "viewer" })) };
}

describe("dashboard", () => {
  it("shows counts and daily activity of the active organization", async () => {
    const { calls } = renderApp({
      routes: { ...signedIn(), ...DASHBOARD_ROUTES, "GET /organizations": organizations(HARBOUR) },
    });

    const overview = await screen.findByRole("region", { name: "Records and open jobs" });
    expect(within(overview).getByText("Documents").nextElementSibling).toHaveTextContent("120");
    expect(within(overview).getByText("Pending ingestion")).toBeInTheDocument();
    const events = screen.getByRole("region", { name: /Events per day/ });
    expect(within(events).getByRole("rowheader", { name: "2026-10-01" })).toBeInTheDocument();
    expect(within(events).getByRole("columnheader", { name: "Cross source clusters" })).toBeInTheDocument();
    for (const path of ["/dashboard/overview", "/dashboard/sources", "/dashboard/events"]) {
      const call = calls.find((item) => item.path === path);
      expect(call.query.get("organization_id")).toBe("org-a");
    }
    expect(calls.find((call) => call.path === "/dashboard/sources").query.get("days")).toBe("14");
  });

  it("switches organization without showing old numbers", async () => {
    const counts = { "org-a": 111, "org-b": 222 };
    let releaseB;
    const bReady = new Promise((resolve) => {
      releaseB = resolve;
    });
    renderApp({
      routes: {
        ...signedIn(),
        ...DASHBOARD_ROUTES,
        "GET /organizations": organizations(HARBOUR, RIVER),
        "GET /dashboard/overview": async ({ query }) => {
          const organization = query.get("organization_id");
          if (organization === "org-b") await bReady;
          return { body: { documents: counts[organization] } };
        },
      },
    });
    const user = userEvent.setup();

    const overview = await screen.findByRole("region", { name: "Records and open jobs" });
    expect(within(overview).getByText("Documents").nextElementSibling).toHaveTextContent("111");

    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    // While B loads, nothing of A is left on the page.
    await waitFor(() => expect(screen.queryByText("111")).not.toBeInTheDocument());
    releaseB();
    expect(await screen.findByText("222")).toBeInTheDocument();
    expect(screen.queryByText("111")).not.toBeInTheDocument();
  });

  it("asks for an organization when there is none, also for system admins", async () => {
    const { calls } = renderApp({
      routes: { ...signedIn(ADMIN), ...DASHBOARD_ROUTES, "GET /organizations": organizations() },
    });

    expect(await screen.findByText("Choose an organization to see its dashboard.")).toBeInTheDocument();
    expect(calls.some((call) => call.path.startsWith("/dashboard"))).toBe(false);
  });

  it("shows an API error", async () => {
    renderApp({
      routes: {
        ...signedIn(),
        ...DASHBOARD_ROUTES,
        "GET /organizations": organizations(HARBOUR),
        "GET /dashboard/overview": {
          status: 503,
          body: { error: { code: "service_unavailable", message: "Database is not configured." } },
        },
      },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("Database is not configured.");
  });
});
