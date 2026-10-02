import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { held, hit, page, source } from "../../test/content.js";
import { signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

const E5 = "intfloat/multilingual-e5-small";

function routes(extra = {}) {
  return {
    ...signedIn(),
    ...organizations([HARBOUR, RIVER]),
    "GET /sources": page([source(), source({ id: "s-2", name: "Harbour Site" })]),
    "GET /search": { body: { items: [hit({ rank: 0.0759 })] } },
    "GET /search/semantic": {
      body: { items: [hit({ excerpt: undefined, similarity: 0.8123 })] },
    },
    "GET /search/hybrid": {
      body: {
        items: [
          hit({ lexical_rank: 1, vector_similarity: 0.8, hybrid_score: 0.0325 }),
          hit({
            chunk_id: "c-2",
            document_id: "d-2",
            title: "Harbour reopens",
            excerpt: null,
            lexical_rank: null,
            vector_similarity: 0.61,
            hybrid_score: 0.0161,
          }),
        ],
      },
    },
    "GET /search/reranked": {
      body: { items: [hit({ hybrid_score: 0.0325, reranker_score: 7.25 })] },
    },
    ...extra,
  };
}

async function runSearch(user, text, mode) {
  const form = await screen.findByRole("search", { name: "Search documents" });
  await user.type(within(form).getByLabelText("Search for"), text);
  if (mode) await user.selectOptions(within(form).getByLabelText("Mode"), mode);
  await user.click(within(form).getByRole("button", { name: "Search" }));
  return screen.findByRole("region", { name: "Results" });
}

function searchCalls(calls) {
  return calls.filter((call) => call.path.startsWith("/search"));
}

describe("search workspace", () => {
  it("runs hybrid search by default and keeps the API's order", async () => {
    const { calls } = renderApp({ path: "/search", routes: routes() });
    const user = userEvent.setup();

    const results = await runSearch(user, "harbour storm");
    const items = await within(results).findAllByRole("listitem");
    expect(items.map((item) => within(item).getByRole("heading").textContent)).toEqual([
      "Storm closes the harbour",
      "Harbour reopens",
    ]);
    expect(within(items[0]).getByText("Hybrid score").nextElementSibling).toHaveTextContent(
      "0.0325",
    );
    expect(within(items[0]).getByText("Lexical position").nextElementSibling).toHaveTextContent(
      "1",
    );
    expect(within(items[1]).queryByText("Lexical position")).not.toBeInTheDocument();
    const [call] = searchCalls(calls);
    expect(call.path).toBe("/search/hybrid");
    expect(call.query.get("q")).toBe("harbour storm");
    expect(call.query.get("model")).toBe(E5);
    expect(call.query.get("organization_id")).toBe("org-a");
  });

  it.each([
    ["lexical", "/search", "Lexical score", "0.0759"],
    ["semantic", "/search/semantic", "Semantic similarity", "0.8123"],
    ["reranked", "/search/reranked", "Reranker score", "7.2500"],
  ])("runs %s search", async (mode, path, label, value) => {
    const { calls } = renderApp({ path: "/search", routes: routes() });
    const user = userEvent.setup();

    const results = await runSearch(user, "harbour", mode);
    const item = await within(results).findByRole("listitem");
    expect(within(item).getByText(label).nextElementSibling).toHaveTextContent(value);
    expect(searchCalls(calls).at(-1).path).toBe(path);
    expect(item).not.toHaveTextContent(/best|trustworthy|correct/i);
  });

  it("links documents and sources and shows the page", async () => {
    renderApp({ path: "/search", routes: routes() });
    const user = userEvent.setup();

    const results = await runSearch(user, "harbour", "lexical");
    const item = await within(results).findByRole("listitem");
    expect(within(item).getByRole("link", { name: "Storm closes the harbour" })).toHaveAttribute(
      "href",
      "/documents/d-1",
    );
    expect(within(item).getByRole("link", { name: "Harbour Feed" })).toHaveAttribute(
      "href",
      "/sources/s-1",
    );
    expect(item).toHaveTextContent("Page 2");
    expect(item).toHaveTextContent("The harbour closed at noon after the storm.");
  });

  it("filters by a source of the active organization", async () => {
    const { calls } = renderApp({ path: "/search", routes: routes() });
    const user = userEvent.setup();

    const form = await screen.findByRole("search", { name: "Search documents" });
    await within(form).findByRole("option", { name: "Harbour Site" });
    await user.selectOptions(within(form).getByLabelText("Source"), "s-2");
    await runSearch(user, "harbour");

    await waitFor(() => expect(searchCalls(calls)).toHaveLength(1));
    expect(searchCalls(calls)[0].query.get("source_id")).toBe("s-2");
  });

  it("loads and selects a source from a later page without duplicates", async () => {
    const { calls } = renderApp({
      path: "/search",
      routes: routes({
        "GET /sources": ({ query }) => {
          if (query.get("offset") === "50") {
            return page([
              source({ id: "s-2", name: "Harbour Site" }),
              source({ id: "s-101", name: "Later Source" }),
            ], { total: 101, offset: 50 });
          }
          return page([source(), source({ id: "s-2", name: "Harbour Site" })], { total: 101 });
        },
      }),
    });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Load more sources" }));
    const form = screen.getByRole("search", { name: "Search documents" });
    await within(form).findByRole("option", { name: "Later Source" });
    expect(within(form).getAllByRole("option", { name: "Harbour Site" })).toHaveLength(1);
    await user.selectOptions(within(form).getByLabelText("Source"), "s-101");
    await runSearch(user, "later");

    expect(searchCalls(calls).at(-1).query.get("source_id")).toBe("s-101");
  });

  it("searches source options on the server", async () => {
    const { calls } = renderApp({ path: "/search", routes: routes() });
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Find source"), "site");

    await waitFor(() =>
      expect(calls.some((call) => call.path === "/sources" && call.query.get("query") === "site"))
        .toBe(true),
    );
  });

  it("explains a model that is not enabled", async () => {
    renderApp({
      path: "/search",
      routes: routes({
        "GET /search/semantic": {
          status: 503,
          body: { error: { code: "service_unavailable", message: "Local embeddings are off." } },
        },
      }),
    });
    const user = userEvent.setup();

    const results = await runSearch(user, "harbour", "semantic");
    const alert = await within(results).findByRole("alert");
    expect(alert).toHaveTextContent("Semantic search is not available: Local embeddings are off.");
    expect(alert).toHaveTextContent("Lexical search works without one.");
  });

  it("says when nothing was found", async () => {
    renderApp({
      path: "/search",
      routes: routes({ "GET /search/hybrid": { body: { items: [] } } }),
    });
    const user = userEvent.setup();

    const results = await runSearch(user, "nothing");
    expect(await within(results).findByText("No results.")).toBeInTheDocument();
  });

  it("restores a search from the URL", async () => {
    const { calls } = renderApp({
      path: "/search?org=org-a&q=storm&mode=lexical&limit=25",
      routes: routes(),
    });

    expect(await screen.findByText("Storm closes the harbour")).toBeInTheDocument();
    expect(screen.getByLabelText("Search for")).toHaveValue("storm");
    expect(searchCalls(calls)[0].query.get("limit")).toBe("25");
  });

  it("clears results when switching organization and does not search again", async () => {
    const river = held();
    const { calls } = renderApp({
      path: "/search",
      routes: routes({
        "GET /sources": async ({ query }) => {
          if (query.get("organization_id") === "org-b") await river.ready;
          return page([source()]);
        },
      }),
    });
    const user = userEvent.setup();

    const results = await runSearch(user, "harbour");
    await within(results).findByText("Storm closes the harbour");
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    await waitFor(() =>
      expect(screen.queryByText("Storm closes the harbour")).not.toBeInTheDocument(),
    );
    river.release();
    expect(await screen.findByLabelText("Search for")).toHaveValue("");
    expect(screen.queryByRole("region", { name: "Results" })).not.toBeInTheDocument();
    expect(searchCalls(calls).every((call) => call.query.get("organization_id") === "org-a")).toBe(
      true,
    );
  });
});
