import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { forbidden, held, investigation, page, savedItem } from "../../test/content.js";
import { USER, signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

const ITEMS = [
  savedItem("source", { name: "Harbour Feed", source_type: "rss", url: null }),
  savedItem(
    "document",
    {
      title: "Storm closes the harbour",
      url: null,
      published_at: "2026-09-05T06:00:00Z",
      source_id: "s-1",
    },
    { label: "Key report" },
  ),
  savedItem("event", { event_type: "storm", title: "Harbour storm", occurred_at: null }),
  savedItem("event_cluster", { event_type: "storm", title: "Storm cluster", occurred_at: null }),
  savedItem("entity", { canonical_name: "Harbour Authority", entity_type: "organization" }),
  savedItem("claim", { text: "Traffic fell by 40 percent", claim_type: "statistic" }),
  savedItem("research_session", {
    title: "Closure questions",
    retrieval_mode: "hybrid",
    source_id: null,
    turn_count: 2,
    latest_turn_at: null,
  }),
];

function routes(extra = {}, role = "owner", user) {
  return {
    ...signedIn(user),
    ...organizations([HARBOUR, RIVER], role),
    "GET /investigations": page([
      investigation(),
      investigation({ id: "inv-2", title: "Ferry strike", status: "closed", description: null }),
    ]),
    "GET /investigations/inv-1": { body: investigation() },
    "GET /investigations/inv-1/items": { body: ITEMS },
    "GET /investigations/inv-1/members": { body: [] },
    "GET /organizations/org-a/members": { body: [] },
    ...extra,
  };
}

function listCalls(calls) {
  return calls.filter((call) => call.path === "/investigations" && call.method === "GET");
}

describe("investigation workspace", () => {
  it("lists the active organization's investigations", async () => {
    const { calls } = renderApp({ path: "/investigations", routes: routes() });

    const link = await screen.findByRole("link", { name: "Harbour closure" });
    expect(link).toHaveAttribute("href", "/investigations/inv-1");
    expect(link.closest("tr")).toHaveTextContent("Why the harbour closed.");
    expect(screen.getByRole("link", { name: "Ferry strike" }).closest("tr")).toHaveTextContent(
      "closed",
    );
    expect(listCalls(calls)[0].query.get("organization_id")).toBe("org-a");
  });

  it("filters by status", async () => {
    const { calls } = renderApp({ path: "/investigations", routes: routes() });
    const user = userEvent.setup();

    await screen.findByText("Harbour closure");
    await user.selectOptions(screen.getByLabelText("Status"), "closed");

    await waitFor(() => expect(listCalls(calls).at(-1).query.get("status")).toBe("closed"));
  });

  it("starts an investigation in the active organization", async () => {
    let posted = null;
    renderApp({
      path: "/investigations",
      routes: routes({
        "POST /investigations": ({ body }) => {
          posted = body;
          return { status: 201, body: investigation({ id: "inv-9", title: body.title }) };
        },
      }),
    });
    const user = userEvent.setup();

    const form = await screen.findByRole("region", { name: "Start an investigation" });
    await user.type(within(form).getByLabelText("Title"), "Fuel prices");
    await user.type(within(form).getByLabelText("Description (optional)"), "Why prices rose.");
    await user.click(within(form).getByRole("button", { name: "Start investigation" }));

    expect(await within(form).findByRole("link", { name: "Open it" })).toHaveAttribute(
      "href",
      "/investigations/inv-9",
    );
    expect(posted).toEqual({
      title: "Fuel prices",
      description: "Why prices rose.",
      organization_id: "org-a",
    });
  });

  it("shows the saved items by type from their snapshots", async () => {
    renderApp({ path: "/investigations/inv-1", routes: routes() });

    const items = await screen.findByRole("region", { name: "Saved items" });
    for (const heading of [
      "Sources",
      "Documents",
      "Events",
      "Event clusters",
      "Entities",
      "Claims",
      "Research sessions",
    ]) {
      expect(within(items).getByRole("region", { name: heading })).toBeInTheDocument();
    }
    expect(within(items).getByRole("link", { name: "Harbour Feed" })).toHaveAttribute(
      "href",
      "/sources/ref-source",
    );
    expect(within(items).getByRole("link", { name: "Storm closes the harbour" })).toHaveAttribute(
      "href",
      "/documents/ref-document",
    );
    expect(within(items).getByText("Key report")).toBeInTheDocument();
    expect(within(items).getByText("Harbour storm").tagName).toBe("SPAN");
    expect(within(items).getByRole("link", { name: "Storm cluster" })).toHaveAttribute(
      "href",
      "/event-clusters/ref-event_cluster",
    );
    expect(within(items).getByRole("link", { name: "Closure questions" })).toHaveAttribute(
      "href",
      "/research/ref-research_session",
    );
    expect(items).toHaveTextContent("hybrid, 2 turns when saved");
  });

  it("closes and reopens", async () => {
    const sent = [];
    renderApp({
      path: "/investigations/inv-1",
      routes: routes({
        "PATCH /investigations/inv-1": ({ body }) => {
          sent.push(body);
          return { body: investigation({ status: body.status }) };
        },
      }),
    });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Close" }));
    expect(
      await screen.findByText(/This investigation is closed and read only/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete investigation" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reopen" }));

    expect(await screen.findByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(sent).toEqual([{ status: "closed" }, { status: "open" }]);
  });

  it("deletes an open investigation after confirmation", async () => {
    let deleted = false;
    renderApp({
      path: "/investigations/inv-1",
      routes: routes({
        "DELETE /investigations/inv-1": () => {
          deleted = true;
          return { status: 204 };
        },
      }),
    });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Delete investigation" }));
    await user.click(screen.getByRole("button", { name: "Yes, delete investigation" }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Investigations" }),
    ).toBeInTheDocument();
    expect(deleted).toBe(true);
  });

  it("shows the API's refusal to a viewer", async () => {
    renderApp({
      path: "/investigations/inv-1",
      routes: routes(
        { "PATCH /investigations/inv-1": forbidden("Only editors can change it.") },
        "viewer",
        USER,
      ),
    });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Close" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Only editors can change it.");
    const overview = screen.getByRole("region", { name: "Overview" });
    expect(within(overview).getByText("Status").nextElementSibling).toHaveTextContent("open");
  });

  it("does not show another organization's investigation", async () => {
    renderApp({
      path: "/investigations/inv-1",
      routes: routes({
        "GET /investigations/inv-1": { body: investigation({ organization_id: "org-b" }) },
      }),
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "does not belong to the active organization",
    );
    expect(screen.queryByText("Harbour Feed")).not.toBeInTheDocument();
  });

  it("drops the old organization's investigations when switching", async () => {
    const river = held();
    const { calls } = renderApp({
      path: "/investigations",
      routes: routes({
        "GET /investigations": async ({ query }) => {
          if (query.get("organization_id") === "org-b") {
            await river.ready;
            return page([
              investigation({ id: "inv-b", title: "River flood", organization_id: "org-b" }),
            ]);
          }
          return page([investigation()]);
        },
      }),
    });
    const user = userEvent.setup();

    await screen.findByText("Harbour closure");
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    await waitFor(() => expect(screen.queryByText("Harbour closure")).not.toBeInTheDocument());
    river.release();
    expect(await screen.findByText("River flood")).toBeInTheDocument();
    expect(listCalls(calls).at(-1).query.get("organization_id")).toBe("org-b");
  });
});
