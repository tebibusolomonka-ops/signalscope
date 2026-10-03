import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { eventDetail, notFound, page, source } from "../../test/content.js";
import { signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

function routes(extra = {}) {
  return {
    ...signedIn(),
    ...organizations([HARBOUR, RIVER]),
    "GET /sources": page([source()]),
    "GET /investigations": page([]),
    "GET /events/ev-1": ({ query }) =>
      query.get("organization_id") === "org-a"
        ? { body: eventDetail() }
        : notFound("Event was not found."),
    ...extra,
  };
}

describe("event detail", () => {
  it("shows the event and its evidence with links", async () => {
    renderApp({ path: "/events/ev-1", routes: routes() });

    expect(
      await screen.findByRole("heading", { level: 1, name: "Storm closes the harbour" }),
    ).toBeInTheDocument();
    const summary = screen.getByRole("region", { name: "Summary" });
    expect(within(summary).getByText("storm")).toBeInTheDocument();
    expect(within(summary).getByText("2026-09-05 00:00 UTC")).toBeInTheDocument();
    expect(summary).toHaveTextContent("The harbour shut at noon.");
    const table = screen.getByRole("table", { name: "Evidence" });
    const row = within(table).getAllByRole("row")[1];
    expect(within(row).getByRole("link", { name: "Harbour Feed" })).toHaveAttribute(
      "href",
      "/sources/s-1",
    );
    expect(within(row).getByRole("link", { name: "Storm report" })).toHaveAttribute(
      "href",
      "/documents/d-1?chunk=c-1",
    );
    expect(row).toHaveTextContent("Page 2");
    expect(row).toHaveTextContent("0.91");
    expect(row).toHaveTextContent("gliner2 / fastino/gliner2.5-multi-v1");
  });

  it("shows an unknown date without inventing one", async () => {
    renderApp({
      path: "/events/ev-1",
      routes: routes({
        "GET /events/ev-1": {
          body: eventDetail({ event: { ...eventDetail().event, occurred_at: null } }),
        },
      }),
    });
    const summary = await screen.findByRole("region", { name: "Summary" });
    expect(within(summary).getByText("Date unknown")).toBeInTheDocument();
  });

  it("shows an unknown event", async () => {
    renderApp({
      path: "/events/ev-9",
      routes: routes({ "GET /events/ev-9": notFound("Event was not found.") }),
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("Event was not found.");
  });

  it("does not keep the event after switching organization", async () => {
    renderApp({ path: "/events/ev-1", routes: routes() });
    const user = userEvent.setup();

    await screen.findByRole("region", { name: "Summary" });
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    expect(await screen.findByText("Event was not found.")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByText("The harbour shut at noon.")).not.toBeInTheDocument(),
    );
  });
});
