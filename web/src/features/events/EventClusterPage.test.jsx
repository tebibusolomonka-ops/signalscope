import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { notFound } from "../../test/content.js";
import { signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

function evidenceRow(overrides = {}) {
  return {
    document_id: "d-1",
    chunk_id: "c-1",
    source_id: "s-1",
    source_name: "Harbour Feed",
    confidence: 0.88,
    provider: "gliner2",
    model: "fastino/gliner2.5-multi-v1",
    chunk_metadata: { page_number: 1 },
    ...overrides,
  };
}

const CLUSTER = {
  cluster_id: "cl-1",
  event_type: "storm",
  title: "Storm closes the harbour",
  occurred_at: "2026-09-05T00:00:00Z",
  event_count: 2,
  source_count: 2,
  evidence_count: 2,
  members: [
    {
      event_id: "ev-1",
      title: "Storm closes the harbour",
      summary: "Ships stayed in port.",
      occurred_at: "2026-09-05T00:00:00Z",
      created_at: "2026-09-05T07:00:00Z",
      evidence: [evidenceRow()],
    },
    {
      event_id: "ev-2",
      title: "Harbour shut by storm",
      summary: null,
      occurred_at: null,
      created_at: "2026-09-05T08:00:00Z",
      evidence: [
        evidenceRow({
          document_id: "d-2",
          chunk_id: "c-2",
          source_id: "s-2",
          source_name: "Harbour Site",
        }),
      ],
    },
  ],
};

function routes(extra = {}) {
  return {
    ...signedIn(),
    ...organizations([HARBOUR, RIVER]),
    "GET /event-clusters/cl-1": ({ query }) =>
      query.get("organization_id") === "org-a"
        ? { body: CLUSTER }
        : notFound("Event cluster was not found."),
    "GET /events/ev-1/link-suggestions": {
      body: [
        {
          candidate_event_id: "ev-9",
          candidate_cluster_id: "cl-9",
          title: "Port closed after gale",
          occurred_at: "2026-09-06T00:00:00Z",
          similarity: 0.9134,
        },
        {
          candidate_event_id: "ev-8",
          candidate_cluster_id: null,
          title: "Gale warning",
          occurred_at: null,
          similarity: 0.71,
        },
      ],
    },
    ...extra,
  };
}

describe("event cluster", () => {
  it("shows the summary, members and their evidence with links", async () => {
    renderApp({ path: "/event-clusters/cl-1", routes: routes() });

    expect(
      await screen.findByRole("heading", { level: 1, name: "Storm closes the harbour" }),
    ).toBeInTheDocument();
    const summary = screen.getByRole("region", { name: "Summary" });
    expect(within(summary).getByText("Sources").nextElementSibling).toHaveTextContent("2");
    const second = screen.getByRole("article", { name: "Harbour shut by storm" });
    expect(second).toHaveTextContent("Occurred: Date unknown");
    const table = within(second).getByRole("table", { name: "Evidence for Harbour shut by storm" });
    expect(within(table).getByRole("link", { name: "Harbour Site" })).toHaveAttribute(
      "href",
      "/sources/s-2",
    );
    expect(within(table).getByRole("link", { name: "Open document" })).toHaveAttribute(
      "href",
      "/documents/d-2?chunk=c-2",
    );
    const first = screen.getByRole("article", { name: "Storm closes the harbour" });
    expect(first).toHaveTextContent("Ships stayed in port.");
    expect(first).toHaveTextContent("Page 1");
  });

  it("loads advisory suggestions on request, with no merge control", async () => {
    const { calls } = renderApp({ path: "/event-clusters/cl-1", routes: routes() });
    const user = userEvent.setup();

    const first = await screen.findByRole("article", { name: "Storm closes the harbour" });
    expect(calls.some((call) => call.path.includes("link-suggestions"))).toBe(false);
    await user.click(within(first).getByRole("button", { name: "Show suggested similar events" }));

    const suggestions = await within(first).findByRole("region", {
      name: "Suggested similar events",
    });
    expect(suggestions).toHaveTextContent("They are suggestions only and are not linked");
    const rows = (await within(suggestions).findAllByRole("row")).slice(1);
    expect(rows[0]).toHaveTextContent("Port closed after gale");
    expect(rows[0]).toHaveTextContent("0.913");
    expect(within(rows[0]).getByRole("link", { name: "Open cluster" })).toHaveAttribute(
      "href",
      "/event-clusters/cl-9",
    );
    expect(rows[1]).toHaveTextContent("None");
    expect(screen.queryByRole("button", { name: /merge|link|join/i })).not.toBeInTheDocument();
    const call = calls.find((item) => item.path === "/events/ev-1/link-suggestions");
    expect(call.query.get("organization_id")).toBe("org-a");
    expect(calls.every((item) => item.method === "GET")).toBe(true);
  });

  it("explains when suggestions need a model that is off", async () => {
    renderApp({
      path: "/event-clusters/cl-1",
      routes: routes({
        "GET /events/ev-1/link-suggestions": {
          status: 503,
          body: { error: { code: "service_unavailable", message: "Local embeddings are off." } },
        },
      }),
    });
    const user = userEvent.setup();

    const first = await screen.findByRole("article", { name: "Storm closes the harbour" });
    await user.click(within(first).getByRole("button", { name: "Show suggested similar events" }));

    expect(await within(first).findByRole("alert")).toHaveTextContent(
      "Suggestions are not available: Local embeddings are off.",
    );
  });

  it("shows an unknown cluster", async () => {
    renderApp({ path: "/event-clusters/cl-9", routes: routes() });
    expect(await screen.findByRole("alert")).toHaveTextContent("Not found.");
  });

  it("does not keep the cluster after switching organization", async () => {
    renderApp({ path: "/event-clusters/cl-1", routes: routes() });
    const user = userEvent.setup();

    await screen.findByRole("region", { name: "Member events" });
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    expect(await screen.findByText("Event cluster was not found.")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByText("Ships stayed in port.")).not.toBeInTheDocument(),
    );
  });
});
