import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { doc, documentChunk, notFound, page, source } from "../../test/content.js";
import { signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

function inHarbour(body, message) {
  return ({ query }) => (query.get("organization_id") === "org-a" ? { body } : notFound(message));
}

// One direct-lookup route per chunk; org B and unknown IDs fall through to 404.
function chunkRoutes(chunks) {
  const routes = {};
  for (const chunk of chunks) {
    routes[`GET /documents/d-1/chunks/${chunk.chunk_id}`] = inHarbour(
      chunk,
      "Document was not found.",
    );
  }
  return routes;
}

function routes(chunks, extra = {}) {
  return {
    ...signedIn(),
    ...organizations([HARBOUR, RIVER]),
    "GET /documents": page([doc()]),
    "GET /documents/d-1": inHarbour(doc(), "Document was not found."),
    "GET /sources/s-1": inHarbour(source(), "Source was not found."),
    "GET /documents/d-1/revisions": { body: { items: [] } },
    ...chunkRoutes(chunks),
    ...extra,
  };
}

const CHUNKS = Array.from({ length: 5 }, (_, index) => documentChunk(index));

function chunkLookups(calls) {
  return calls.filter((call) => /^\/documents\/d-1\/chunks\/[^/]+$/.test(call.path));
}

describe("document evidence focus", () => {
  it("focuses and highlights the chunk from the URL", async () => {
    renderApp({ path: "/documents/d-1?chunk=c-3", routes: routes(CHUNKS) });

    const panel = await screen.findByRole("region", { name: "Focused evidence" });
    const evidence = await within(panel).findByLabelText("Evidence at position 4");
    expect(evidence).toHaveTextContent("Chunk 3 about the harbour.");
    expect(evidence).toHaveTextContent("Page 4");
    await waitFor(() => expect(evidence).toHaveFocus());
  });

  it("finds a very late chunk with one direct request, no paging", async () => {
    const many = Array.from({ length: 300 }, (_, index) => documentChunk(index));
    const { calls } = renderApp({ path: "/documents/d-1?chunk=c-275", routes: routes(many) });

    const panel = await screen.findByRole("region", { name: "Focused evidence" });
    expect(await within(panel).findByText("Chunk 275 about the harbour.")).toBeInTheDocument();
    const lookups = chunkLookups(calls);
    expect(lookups).toHaveLength(1);
    expect(lookups[0].path).toBe("/documents/d-1/chunks/c-275");
    expect(calls.some((call) => call.path === "/documents/d-1/chunks")).toBe(false);
  });

  it("shows a non-fatal message for an unknown chunk and keeps the page", async () => {
    renderApp({ path: "/documents/d-1?chunk=c-missing", routes: routes(CHUNKS) });

    const panel = await screen.findByRole("region", { name: "Focused evidence" });
    expect(await within(panel).findByText(/was not found/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Text" })).toHaveTextContent(
      "The harbour closed at noon.",
    );
  });

  it("shows no focus panel on the normal document route", async () => {
    renderApp({ path: "/documents/d-1", routes: routes(CHUNKS) });

    await screen.findByRole("region", { name: "Details" });
    expect(screen.queryByRole("region", { name: "Focused evidence" })).not.toBeInTheDocument();
  });

  it("drops the focused chunk when switching organization", async () => {
    renderApp({ path: "/documents/d-1?chunk=c-3", routes: routes(CHUNKS) });
    const user = userEvent.setup();

    await screen.findByLabelText("Evidence at position 4");
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    expect(await screen.findByText("Document was not found.")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByText("Chunk 3 about the harbour.")).not.toBeInTheDocument(),
    );
  });
});
