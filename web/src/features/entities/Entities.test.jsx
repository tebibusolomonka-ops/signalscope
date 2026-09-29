import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { entity, evidence, held, notFound, page } from "../../test/content.js";
import { signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

function detail(overrides = {}) {
  return {
    body: {
      entity: entity(),
      mention_count: 3,
      mentions: [evidence(), evidence({ id: "m-2", document_id: "d-2", chunk_metadata: {} })],
      ...overrides,
    },
  };
}

function routes(extra = {}) {
  return {
    ...signedIn(),
    ...organizations([HARBOUR, RIVER]),
    "GET /entities": page([
      entity(),
      entity({ id: "e-2", canonical_name: "Ana Ruiz", entity_type: "person", mention_count: 1 }),
    ]),
    "GET /entities/e-1": ({ query }) =>
      query.get("organization_id") === "org-a" ? detail() : notFound("Entity was not found."),
    ...extra,
  };
}

function entityCalls(calls) {
  return calls.filter((call) => call.path === "/entities");
}

describe("entity workspace", () => {
  it("lists entities with the organization's mention counts", async () => {
    const { calls } = renderApp({ path: "/entities", routes: routes() });

    const link = await screen.findByRole("link", { name: "Harbour Authority" });
    expect(link).toHaveAttribute("href", "/entities/e-1");
    const row = link.closest("tr");
    expect(row).toHaveTextContent("organization");
    expect(row).toHaveTextContent("3");
    expect(screen.getByText(/Mention counts cover this organization only/)).toBeInTheDocument();
    expect(entityCalls(calls)[0].query.get("organization_id")).toBe("org-a");
  });

  it("filters by name and type", async () => {
    const { calls } = renderApp({ path: "/entities", routes: routes() });
    const user = userEvent.setup();

    const form = await screen.findByRole("search", { name: "Filter entities" });
    await user.type(within(form).getByLabelText("Name contains"), "ruiz");
    await user.type(within(form).getByLabelText("Type"), "person");
    await user.click(within(form).getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(entityCalls(calls).at(-1).query.get("query")).toBe("ruiz"));
    expect(entityCalls(calls).at(-1).query.get("entity_type")).toBe("person");
    expect(entityCalls(calls).at(-1).query.get("offset")).toBe("0");
  });

  it("pages with the API", async () => {
    const { calls } = renderApp({
      path: "/entities",
      routes: routes({
        "GET /entities": ({ query }) =>
          query.get("offset") === "50"
            ? page([entity({ id: "e-51", canonical_name: "Late Name" })], { total: 51, offset: 50 })
            : page([entity()], { total: 51 }),
      }),
    });
    const user = userEvent.setup();

    await screen.findByText("Harbour Authority");
    await user.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("Late Name")).toBeInTheDocument();
    expect(entityCalls(calls).at(-1).query.get("offset")).toBe("50");
  });

  it("shows the mentions of one entity with document links", async () => {
    renderApp({ path: "/entities/e-1", routes: routes() });

    expect(
      await screen.findByRole("heading", { level: 1, name: "Harbour Authority" }),
    ).toBeInTheDocument();
    const summary = screen.getByRole("region", { name: "Summary" });
    expect(
      within(summary).getByText("Mentions in this organization").nextElementSibling,
    ).toHaveTextContent("3");
    const table = screen.getByRole("table", { name: "Mentions" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByRole("link", { name: "Open document" })).toHaveAttribute(
      "href",
      "/documents/d-1",
    );
    expect(rows[0]).toHaveTextContent("the Harbour Authority");
    expect(rows[0]).toHaveTextContent("Page 2");
    expect(rows[0]).toHaveTextContent("0.91");
    expect(rows[0]).toHaveTextContent("gliner / urchade/gliner_multi-v2.1");
    expect(screen.getByText("The first 2 of 3 mentions, in document order.")).toBeInTheDocument();
  });

  it("shows an entity with no mentions here as not found", async () => {
    renderApp({
      path: "/entities/e-9",
      routes: routes({ "GET /entities/e-9": notFound("Entity was not found.") }),
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("Entity was not found.");
  });

  it("drops the list when switching organization", async () => {
    const river = held();
    renderApp({
      path: "/entities",
      routes: routes({
        "GET /entities": async ({ query }) => {
          if (query.get("organization_id") === "org-b") {
            await river.ready;
            return page([entity({ id: "e-b", canonical_name: "River Council" })]);
          }
          return page([entity()]);
        },
      }),
    });
    const user = userEvent.setup();

    await screen.findByText("Harbour Authority");
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    await waitFor(() => expect(screen.queryByText("Harbour Authority")).not.toBeInTheDocument());
    river.release();
    expect(await screen.findByText("River Council")).toBeInTheDocument();
  });

  it("does not keep the detail after switching organization", async () => {
    renderApp({ path: "/entities/e-1", routes: routes() });
    const user = userEvent.setup();

    await screen.findByRole("table", { name: "Mentions" });
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    expect(await screen.findByText("Entity was not found.")).toBeInTheDocument();
    expect(screen.queryByText("the Harbour Authority")).not.toBeInTheDocument();
  });
});
