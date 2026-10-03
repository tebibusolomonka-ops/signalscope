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

function chunksRoute(chunks) {
  return ({ query }) => {
    if (query.get("organization_id") !== "org-a") return notFound("Document was not found.");
    const limit = Number(query.get("limit") ?? 50);
    const offset = Number(query.get("offset") ?? 0);
    return {
      body: { items: chunks.slice(offset, offset + limit), total: chunks.length, limit, offset },
    };
  };
}

function routes(chunks, extra = {}) {
  return {
    ...signedIn(),
    ...organizations([HARBOUR, RIVER]),
    "GET /documents": page([doc()]),
    "GET /documents/d-1": inHarbour(doc(), "Document was not found."),
    "GET /sources/s-1": inHarbour(source(), "Source was not found."),
    "GET /documents/d-1/revisions": { body: { items: [] } },
    "GET /documents/d-1/chunks": chunksRoute(chunks),
    ...extra,
  };
}

const CHUNKS = Array.from({ length: 5 }, (_, index) => documentChunk(index));

describe("document evidence focus", () => {
  it("focuses and highlights the chunk from the URL", async () => {
    renderApp({ path: "/documents/d-1?chunk=c-3", routes: routes(CHUNKS) });

    const panel = await screen.findByRole("region", { name: "Focused evidence" });
    const evidence = await within(panel).findByLabelText("Evidence at position 4");
    expect(evidence).toHaveTextContent("Chunk 3 about the harbour.");
    expect(evidence).toHaveTextContent("Page 4");
    await waitFor(() => expect(evidence).toHaveFocus());
  });

  it("finds a chunk on a later page", async () => {
    const many = Array.from({ length: 60 }, (_, index) => documentChunk(index));
    const { calls } = renderApp({ path: "/documents/d-1?chunk=c-55", routes: routes(many) });

    const panel = await screen.findByRole("region", { name: "Focused evidence" });
    expect(await within(panel).findByText("Chunk 55 about the harbour.")).toBeInTheDocument();
    const chunkCalls = calls.filter((call) => call.path === "/documents/d-1/chunks");
    expect(chunkCalls.length).toBeGreaterThan(1);
    expect(chunkCalls.every((call) => call.query.get("organization_id") === "org-a")).toBe(true);
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
