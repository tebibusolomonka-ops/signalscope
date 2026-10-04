import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { held, operationsOverview } from "../../test/content.js";
import { USER, signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

function routes(extra = {}, role = "owner", user) {
  return {
    ...signedIn(user),
    ...organizations([HARBOUR, RIVER], role),
    "GET /operations/overview": {
      body: operationsOverview({
        embedding: {
          pending_count: 3,
          running_count: 1,
          failed_count: 2,
          oldest_pending_at: "2026-09-10T08:00:00Z",
          oldest_failed_at: "2026-09-11T09:30:00Z",
        },
      }),
    },
    "GET /operations/history": { body: { items: [], total: 0, limit: 20, offset: 0 } },
    "GET /operations/trends": {
      body: { organization_id: "org-a", bucket: "day", points: [], latency: [] },
    },
    ...extra,
  };
}

function overviewCalls(calls) {
  return calls.filter((call) => call.path === "/operations/overview");
}

describe("operations workspace", () => {
  it("shows paged operation history with safe resource links", async () => {
    renderApp({
      path: "/operations",
      routes: routes({
        "GET /operations/history": {
          body: {
            items: [
              {
                id: "attempt-1",
                queue_name: "processing",
                resource_type: "document",
                resource_id: "doc-1",
                attempt_number: 2,
                outcome: "failed",
                started_at: "2026-10-02T10:00:00Z",
                finished_at: "2026-10-02T10:01:00Z",
                safe_error: "Parser failed.",
              },
            ],
            total: 1,
            limit: 20,
            offset: 0,
          },
        },
      }),
    });

    const history = await screen.findByRole("region", { name: "Operation history" });
    expect(await within(history).findByRole("link", { name: "document doc-1" })).toHaveAttribute(
      "href",
      "/documents/doc-1",
    );
    expect(history).toHaveTextContent("Parser failed.");
    expect(history).toHaveTextContent("2");
  });

  it("sends history filters and clears paging", async () => {
    const { calls } = renderApp({ path: "/operations", routes: routes() });
    const user = userEvent.setup();
    const history = await screen.findByRole("region", { name: "Operation history" });

    await user.selectOptions(within(history).getByLabelText("Queue"), "embedding");
    await user.selectOptions(within(history).getByLabelText("Outcome"), "recovered");

    await waitFor(() => {
      const call = calls.filter((item) => item.path === "/operations/history").at(-1);
      expect(call.query.get("queue")).toBe("embedding");
      expect(call.query.get("outcome")).toBe("recovered");
      expect(call.query.get("offset")).toBe("0");
    });
  });

  it("shows one row per queue with its counts", async () => {
    const { calls } = renderApp({ path: "/operations", routes: routes() });

    const embedding = (await screen.findByRole("rowheader", { name: "Embedding" })).closest("tr");
    const section = screen.getByRole("region", { name: "Queues" });
    expect(
      within(embedding)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual(["3", "1", "2", "2026-09-10 08:00 UTC", "2026-09-11 09:30 UTC"]);
    const ingestion = within(section).getByRole("rowheader", { name: "Ingestion" }).closest("tr");
    expect(
      within(ingestion)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual(["0", "0", "0", "-", "-"]);
    expect(within(section).getAllByRole("rowheader")).toHaveLength(6);
    expect(overviewCalls(calls)[0].query.get("organization_id")).toBe("org-a");
  });

  it("reloads on refresh", async () => {
    const { calls } = renderApp({ path: "/operations", routes: routes() });
    const user = userEvent.setup();

    await screen.findByRole("region", { name: "Queues" });
    await user.click(screen.getByRole("button", { name: "Refresh" }));

    await waitFor(() => expect(overviewCalls(calls).length).toBeGreaterThan(1));
  });

  it("shows the API error", async () => {
    renderApp({
      path: "/operations",
      routes: routes({
        "GET /operations/overview": {
          status: 503,
          body: { error: { code: "service_unavailable", message: "Database is not configured." } },
        },
      }),
    });
    const queues = await screen.findByRole("region", { name: "Queues" });
    expect(await within(queues).findByRole("alert")).toHaveTextContent("Database is not configured.");
  });

  it("tells members they cannot see operations", async () => {
    const { calls } = renderApp({ path: "/operations", routes: routes({}, "member", USER) });

    expect(
      await screen.findByText("Only organization owners and admins can see operations."),
    ).toBeInTheDocument();
    expect(overviewCalls(calls)).toHaveLength(0);
  });

  it("drops the old organization's counts when switching", async () => {
    const river = held();
    renderApp({
      path: "/operations",
      routes: routes({
        "GET /operations/overview": async ({ query }) => {
          if (query.get("organization_id") === "org-b") {
            await river.ready;
            return { body: operationsOverview({ ingestion: { pending_count: 99 } }) };
          }
          return { body: operationsOverview({ embedding: { pending_count: 3 } }) };
        },
      }),
    });
    const user = userEvent.setup();

    const row = (await screen.findByRole("rowheader", { name: "Embedding" })).closest("tr");
    expect(row).toHaveTextContent("3");
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    // While B loads, A's counts are gone; A's answer never fills B's page.
    await waitFor(() =>
      expect(screen.queryByRole("rowheader", { name: "Embedding" })).not.toBeInTheDocument(),
    );
    river.release();
    expect(await screen.findByRole("rowheader", { name: "Ingestion" })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "Ingestion" }).closest("tr")).toHaveTextContent(
      "99",
    );
  });

  it("shows attempt trends and queue latency", async () => {
    const trends = {
      organization_id: "org-a",
      bucket: "day",
      points: [
        {
          bucket_start: "2026-01-01T00:00:00Z",
          total: 5,
          succeeded: 3,
          failed: 1,
          recovered: 1,
          running: 0,
          retried: 2,
        },
      ],
      latency: [
        {
          queue: "ingestion",
          completed: 4,
          min_seconds: 1,
          max_seconds: 9,
          average_seconds: 5,
          p50_seconds: 5,
          p95_seconds: 9,
        },
      ],
    };
    renderApp({ path: "/operations", routes: routes({ "GET /operations/trends": { body: trends } }) });

    const section = await screen.findByRole("region", { name: "Operation trends" });
    expect(await within(section).findByRole("table", { name: "Attempt trends" })).toHaveTextContent(
      "5",
    );
    const latency = within(section).getByRole("table", { name: "Queue latency" });
    expect(latency).toHaveTextContent("Ingestion");
    expect(latency).toHaveTextContent("9");
  });

  it("filters trends by queue and bucket", async () => {
    const { calls } = renderApp({ path: "/operations", routes: routes() });
    const user = userEvent.setup();

    await screen.findByRole("region", { name: "Operation trends" });
    await user.selectOptions(screen.getByLabelText("Trend queue"), "embedding");

    await waitFor(() =>
      expect(
        calls.some(
          (call) =>
            call.path === "/operations/trends" && call.query.get("queue") === "embedding",
        ),
      ).toBe(true),
    );
  });

  it("shows an empty trends message", async () => {
    renderApp({ path: "/operations", routes: routes() });

    const section = await screen.findByRole("region", { name: "Operation trends" });
    expect(await within(section).findByText("No attempts in this range.")).toBeInTheDocument();
  });
});
