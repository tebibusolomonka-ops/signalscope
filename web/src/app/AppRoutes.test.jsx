import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DASHBOARD_ROUTES } from "../test/dashboardRoutes.js";
import { signedIn } from "../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../test/organizations.js";
import { renderApp } from "../test/renderApp.jsx";

const CONTENT = [
  "Dashboard",
  "Sources",
  "Documents",
  "Search",
  "Entities",
  "Claims",
  "Events",
  "Investigations",
  "Research",
  "Operations",
];

function routes(items = [HARBOUR, RIVER]) {
  return { ...signedIn(), ...DASHBOARD_ROUTES, ...organizations(items) };
}

describe("AppRoutes", () => {
  it("renders content and administration navigation", async () => {
    renderApp({ routes: routes() });

    expect(await screen.findByRole("heading", { level: 1, name: "Dashboard" })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Main" });
    const content = within(nav).getByRole("list", { name: "Content" });
    for (const label of CONTENT) {
      expect(within(content).getByRole("link", { name: label })).toBeInTheDocument();
    }
    const admin = within(nav).getByRole("list", { name: "Administration" });
    for (const label of ["Organizations", "Users", "Security", "Evaluations"]) {
      expect(within(admin).getByRole("link", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole("main")).toBeInTheDocument();
  });

  it("marks the current page and follows links with the keyboard", async () => {
    renderApp({ routes: routes() });
    const user = userEvent.setup();

    const dashboard = await screen.findByRole("link", { name: "Dashboard" });
    expect(dashboard).toHaveAttribute("aria-current", "page");
    const sources = screen.getByRole("link", { name: "Sources" });
    sources.focus();
    await user.keyboard("{Enter}");

    expect(await screen.findByRole("heading", { level: 1, name: "Sources" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sources" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Dashboard" })).not.toHaveAttribute("aria-current");
  });

  it.each([
    ["/organizations", "Organizations"],
    ["/users", "Users"],
    ["/security", "Security"],
    ["/nowhere", "Page not found"],
    ["/", "Dashboard"],
    ["/sources", "Sources"],
    ["/research", "Research"],
  ])("routes %s", async (path, title) => {
    renderApp({ path, routes: routes() });
    expect(await screen.findByRole("heading", { level: 1, name: title })).toBeInTheDocument();
  });

  it("asks for an organization on content pages, also for system admins", async () => {
    const { calls } = renderApp({ path: "/search", routes: routes([]) });

    expect(
      await screen.findByRole("heading", { name: "No organization selected" }),
    ).toBeInTheDocument();
    expect(calls.some((call) => call.query.has("organization_id"))).toBe(false);
    expect(calls.some((call) => call.path.startsWith("/dashboard"))).toBe(false);
  });

  it("keeps administration pages without an organization", async () => {
    renderApp({
      path: "/users",
      routes: {
        ...routes([]),
        "GET /admin/users": { body: { items: [], total: 0, limit: 50, offset: 0 } },
      },
    });

    expect(await screen.findByRole("heading", { level: 1, name: "Users" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Security" })).toBeInTheDocument();
    expect(screen.queryByText("No organization selected")).not.toBeInTheDocument();
  });

  it("clears the page of the old organization when switching", async () => {
    let releaseB;
    const bReady = new Promise((resolve) => {
      releaseB = resolve;
    });
    renderApp({
      routes: {
        ...routes(),
        "GET /dashboard/overview": async ({ query }) => {
          if (query.get("organization_id") === "org-b") await bReady;
          return { body: { documents: query.get("organization_id") === "org-a" ? 101 : 202 } };
        },
      },
    });
    const user = userEvent.setup();

    expect(await screen.findByText("101")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    await waitFor(() => expect(screen.queryByText("101")).not.toBeInTheDocument());
    expect(
      screen.queryByText("Harbour Watch", { selector: ".page-heading *" }),
    ).not.toBeInTheDocument();
    releaseB();
    expect(await screen.findByText("202")).toBeInTheDocument();
  });
});
