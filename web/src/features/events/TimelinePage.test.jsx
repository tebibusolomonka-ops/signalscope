import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { held, page, source } from "../../test/content.js";
import { signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

function item(overrides = {}) {
  return {
    cluster_id: "cl-1",
    event_type: "storm",
    title: "Storm closes the harbour",
    occurred_at: "2026-09-05T00:00:00Z",
    event_count: 3,
    source_count: 2,
    evidence_count: 5,
    sources: [
      { source_id: "s-1", name: "Harbour Feed" },
      { source_id: "s-2", name: "Harbour Site" },
    ],
    ...overrides,
  };
}

function routes(extra = {}) {
  return {
    ...signedIn(),
    ...organizations([HARBOUR, RIVER]),
    "GET /sources": page([source()]),
    "GET /timeline": page([
      item(),
      item({ cluster_id: "cl-2", title: "Ferry strike", occurred_at: null, sources: [] }),
    ]),
    ...extra,
  };
}

function timelineCalls(calls) {
  return calls.filter((call) => call.path === "/timeline");
}

describe("event timeline", () => {
  it("shows clusters with their counts and links", async () => {
    const { calls } = renderApp({ path: "/events", routes: routes() });

    const link = await screen.findByRole("link", { name: "Storm closes the harbour" });
    expect(link).toHaveAttribute("href", "/event-clusters/cl-1");
    const row = link.closest("tr");
    const cells = within(row)
      .getAllByRole("cell")
      .map((cell) => cell.textContent);
    expect(cells).toEqual([
      "2026-09-05 00:00 UTC",
      "Storm closes the harbour",
      "storm",
      "2: Harbour Feed, Harbour Site",
      "3",
      "5",
    ]);
    expect(within(row).getByRole("link", { name: "Harbour Site" })).toHaveAttribute(
      "href",
      "/sources/s-2",
    );
    expect(timelineCalls(calls)[0].query.get("organization_id")).toBe("org-a");
    expect(timelineCalls(calls)[0].query.get("order")).toBe("newest_first");
  });

  it("shows an unknown date without making one up", async () => {
    renderApp({ path: "/events", routes: routes() });

    const row = (await screen.findByRole("link", { name: "Ferry strike" })).closest("tr");
    expect(within(row).getAllByRole("cell")[0]).toHaveTextContent("Date unknown");
  });

  it("filters by type, dates, source and order", async () => {
    const { calls } = renderApp({ path: "/events", routes: routes() });
    const user = userEvent.setup();

    const form = await screen.findByRole("search", { name: "Filter events" });
    await within(form).findByRole("option", { name: "Harbour Feed" });
    await user.type(within(form).getByLabelText("Event type"), "storm");
    await user.type(within(form).getByLabelText("From (UTC)"), "2026-09-01");
    await user.type(within(form).getByLabelText("To (UTC)"), "2026-09-30");
    await user.selectOptions(within(form).getByLabelText("Source"), "s-1");
    await user.selectOptions(within(form).getByLabelText("Order"), "oldest_first");
    await user.click(within(form).getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(timelineCalls(calls)).toHaveLength(2));
    const query = timelineCalls(calls)[1].query;
    expect(query.get("event_type")).toBe("storm");
    expect(query.get("occurred_from")).toBe("2026-09-01T00:00:00Z");
    expect(query.get("occurred_to")).toBe("2026-10-01T00:00:00Z");
    expect(query.get("source_id")).toBe("s-1");
    expect(query.get("order")).toBe("oldest_first");
  });

  it("offers sources from beyond the first page in the filter", async () => {
    renderApp({
      path: "/events",
      routes: routes({
        "GET /sources": ({ query }) =>
          query.get("offset") === "0"
            ? page([source()], { total: 2, limit: 100 })
            : page([source({ id: "s-9", name: "Deep Source" })], {
                total: 2,
                limit: 100,
                offset: 1,
              }),
      }),
    });

    const form = await screen.findByRole("search", { name: "Filter events" });
    expect(await within(form).findByRole("option", { name: "Deep Source" })).toBeInTheDocument();
  });

  it("says when there are no events", async () => {
    renderApp({ path: "/events", routes: routes({ "GET /timeline": page([]) }) });
    expect(await screen.findByText("No events match.")).toBeInTheDocument();
  });

  it("shows the API's refusal of a date range", async () => {
    renderApp({
      path: "/events",
      routes: routes({
        "GET /timeline": {
          status: 422,
          body: {
            error: { code: "invalid_input", message: "occurred_from must be before occurred_to." },
          },
        },
      }),
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "occurred_from must be before occurred_to.",
    );
  });

  it("drops the old organization's events when switching", async () => {
    const river = held();
    renderApp({
      path: "/events",
      routes: routes({
        "GET /timeline": async ({ query }) => {
          if (query.get("organization_id") === "org-b") {
            await river.ready;
            return page([item({ cluster_id: "cl-b", title: "River bursts its banks" })]);
          }
          return page([item()]);
        },
      }),
    });
    const user = userEvent.setup();

    await screen.findByText("Storm closes the harbour");
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    await waitFor(() =>
      expect(screen.queryByText("Storm closes the harbour")).not.toBeInTheDocument(),
    );
    river.release();
    expect(await screen.findByText("River bursts its banks")).toBeInTheDocument();
  });
});
