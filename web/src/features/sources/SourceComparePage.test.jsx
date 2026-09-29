import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { held, page, provenance, source } from "../../test/content.js";
import { signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

const RANKING = /winner|best|worst|better|worse|rank #|credib|trust score|reliab/i;

const SOURCES = [
  source(),
  source({ id: "s-2", name: "Harbour Site", type: "web" }),
  source({ id: "s-3", name: "Harbour Radio", type: "api" }),
];

function comparison(ids) {
  return {
    body: {
      sources: ids.map((id, index) => ({
        source: SOURCES.find((item) => item.id === id),
        provenance: provenance({ source_id: id, document_count: 10 + index, claim_count: index }),
      })),
      shared_event_cluster_count: 4,
      shared_entity_count: 9,
      shared_claim_count: 1,
    },
  };
}

function routes(extra = {}) {
  return {
    ...signedIn(),
    ...organizations([HARBOUR, RIVER]),
    "GET /sources": page(SOURCES),
    "POST /sources/compare": ({ body }) => comparison(body.source_ids),
    ...extra,
  };
}

async function choose(user, ...names) {
  const group = await screen.findByRole("group", { name: "Choose 2 to 10 sources" });
  for (const name of names) {
    await user.click(within(group).getByRole("checkbox", { name: new RegExp(name) }));
  }
}

describe("source comparison", () => {
  it("compares two sources side by side", async () => {
    const { calls } = renderApp({ path: "/sources/compare", routes: routes() });
    const user = userEvent.setup();

    await choose(user, "Harbour Feed", "Harbour Site");
    await user.click(screen.getByRole("button", { name: "Compare" }));

    const result = await screen.findByRole("region", { name: "Side by side" });
    const headers = within(result)
      .getAllByRole("columnheader")
      .map((cell) => cell.textContent);
    expect(headers).toEqual(["Observed", "Harbour Feed", "Harbour Site"]);
    expect(within(result).getByRole("link", { name: "Harbour Site" })).toHaveAttribute(
      "href",
      "/sources/s-2",
    );
    const documents = within(result).getByRole("rowheader", { name: "Documents" }).closest("tr");
    expect(
      within(documents)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual(["10", "11"]);
    const call = calls.find((item) => item.path === "/sources/compare");
    expect(call.body).toEqual({ source_ids: ["s-1", "s-2"], organization_id: "org-a" });
  });

  it("compares three sources in the chosen order and shows what they share", async () => {
    renderApp({ path: "/sources/compare", routes: routes() });
    const user = userEvent.setup();

    await choose(user, "Harbour Radio", "Harbour Feed", "Harbour Site");
    await user.click(screen.getByRole("button", { name: "Compare" }));

    const result = await screen.findByRole("region", { name: "Side by side" });
    expect(
      within(result)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual(["Observed", "Harbour Radio", "Harbour Feed", "Harbour Site"]);
    expect(
      within(result).getByText("Entities found in two or more of these sources").nextElementSibling,
    ).toHaveTextContent("9");
    expect(
      within(result).getByText("Event clusters reported by two or more of these sources")
        .nextElementSibling,
    ).toHaveTextContent("4");
    expect(result).not.toHaveTextContent(RANKING);
    expect(result.querySelector("[class*='win'], [class*='best']")).toBeNull();
  });

  it("needs at least two sources", async () => {
    const { calls } = renderApp({ path: "/sources/compare", routes: routes() });
    const user = userEvent.setup();

    await choose(user, "Harbour Feed");

    expect(screen.getByText("Choose at least 2 sources.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Compare" })).toBeDisabled();
    expect(calls.some((call) => call.path === "/sources/compare")).toBe(false);
  });

  it("shows the API's refusal", async () => {
    renderApp({
      path: "/sources/compare",
      routes: routes({
        "POST /sources/compare": {
          status: 404,
          body: { error: { code: "not_found", message: "Source was not found." } },
        },
      }),
    });
    const user = userEvent.setup();

    await choose(user, "Harbour Feed", "Harbour Site");
    await user.click(screen.getByRole("button", { name: "Compare" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Source was not found.");
  });

  it("clears the selection and result when switching organization", async () => {
    const river = held();
    renderApp({
      path: "/sources/compare",
      routes: routes({
        "GET /sources": async ({ query }) => {
          if (query.get("organization_id") === "org-b") {
            await river.ready;
            return page([
              source({ id: "s-b1", name: "River Feed" }),
              source({ id: "s-b2", name: "River Site" }),
            ]);
          }
          return page(SOURCES);
        },
      }),
    });
    const user = userEvent.setup();

    await choose(user, "Harbour Feed", "Harbour Site");
    await user.click(screen.getByRole("button", { name: "Compare" }));
    await screen.findByRole("region", { name: "Side by side" });
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Side by side" })).not.toBeInTheDocument(),
    );
    river.release();
    const group = await screen.findByRole("group", { name: "Choose 2 to 10 sources" });
    expect(
      within(group)
        .getAllByRole("checkbox")
        .every((box) => !box.checked),
    ).toBe(true);
    expect(screen.queryByText("Harbour Feed (rss)")).not.toBeInTheDocument();
  });
});
