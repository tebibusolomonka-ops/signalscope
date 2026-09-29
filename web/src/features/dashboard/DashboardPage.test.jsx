import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DASHBOARD_ROUTES } from "../../test/dashboardRoutes.js";
import { signedIn } from "../../test/fakeApi.js";
import { renderApp } from "../../test/renderApp.jsx";

describe("dashboard", () => {
  it("shows counts and daily activity", async () => {
    const { calls } = renderApp({ routes: { ...signedIn(), ...DASHBOARD_ROUTES } });

    const overview = await screen.findByRole("region", { name: "Records and open jobs" });
    expect(within(overview).getByText("Documents").nextElementSibling).toHaveTextContent("120");
    expect(within(overview).getByText("Pending ingestion")).toBeInTheDocument();
    const events = screen.getByRole("region", { name: /Events per day/ });
    expect(within(events).getByRole("rowheader", { name: "2026-10-01" })).toBeInTheDocument();
    expect(within(events).getByRole("columnheader", { name: "Cross source clusters" })).toBeInTheDocument();
    const sources = calls.find((call) => call.path === "/dashboard/sources");
    expect(sources.query.get("days")).toBe("14");
  });

  it("shows an API error", async () => {
    renderApp({
      routes: {
        ...signedIn(),
        ...DASHBOARD_ROUTES,
        "GET /dashboard/overview": {
          status: 503,
          body: { error: { code: "service_unavailable", message: "Database is not configured." } },
        },
      },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("Database is not configured.");
  });
});
