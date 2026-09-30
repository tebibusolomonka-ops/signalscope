import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { notFound } from "../../test/content.js";
import { signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

function eventDetail(overrides = {}) {
  return {
    event: {
      id: "ev-1",
      event_type: "storm",
      title: "Storm closes the harbour",
      summary: "Ships stayed in port.",
      occurred_at: "2026-09-05T00:00:00Z",
      created_at: "2026-09-05T07:00:00Z",
    },
    evidence: [
      {
        document_id: "d-1",
        chunk_id: "c-1",
        confidence: 0.91,
        provider: "gliner2",
        model: "fastino/gliner2.5-multi-v1",
        chunk_metadata: { page_number: 1 },
      },
    ],
    ...overrides,
  };
}

function routes(extra = {}) {
  return {
    ...signedIn(),
    ...organizations([HARBOUR, RIVER]),
    "GET /events/ev-1": ({ query }) =>
      query.get("organization_id") === "org-a"
        ? { body: eventDetail() }
        : notFound("Event was not found."),
    ...extra,
  };
}

describe("event page", () => {
  it("shows the event fields and its evidence with a document link", async () => {
    renderApp({ path: "/events/ev-1", routes: routes() });

    expect(
      await screen.findByRole("heading", { level: 1, name: "Storm closes the harbour" }),
    ).toBeInTheDocument();
    const summary = screen.getByRole("region", { name: "Summary" });
    expect(within(summary).getByText("Event type").nextElementSibling).toHaveTextContent("storm");
    expect(within(summary).getByText("Occurred").nextElementSibling).toHaveTextContent(
      "2026-09-05 00:00 UTC",
    );
    const evidence = screen.getByRole("region", { name: "Evidence" });
    expect(within(evidence).getByRole("link", { name: "Open document" })).toHaveAttribute(
      "href",
      "/documents/d-1",
    );
    expect(within(evidence).getByText("Page 1")).toBeInTheDocument();
  });

  it("shows an event that is not found", async () => {
    renderApp({
      path: "/events/ev-9",
      routes: routes({ "GET /events/ev-9": notFound("Event was not found.") }),
    });

    expect(await screen.findByText("Event was not found.")).toBeInTheDocument();
  });
});
