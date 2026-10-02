import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { held, notFound, page, provenance, run, source } from "../../test/content.js";
import { USER, signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

function routes(extra = {}, role = "owner", user) {
  return {
    ...signedIn(user),
    ...organizations([HARBOUR, RIVER], role),
    "GET /sources/s-1": ({ query }) =>
      query.get("organization_id") === "org-a"
        ? { body: source() }
        : notFound("Source was not found."),
    "GET /sources/s-1/provenance": { body: provenance() },
    "GET /ingestion-runs": page([run()]),
    ...extra,
  };
}

async function ingestion() {
  return screen.findByRole("region", { name: "Ingestion" });
}

describe("source operations", () => {
  afterEach(() => vi.useRealTimers());

  it("shows the newest runs first, from the last page", async () => {
    const older = Array.from({ length: 10 }, (_, index) =>
      run({
        id: `r-${index}`,
        created_at: `2026-09-${String(index + 10).padStart(2, "0")}T08:00:00Z`,
      }),
    );
    const { calls } = renderApp({
      path: "/sources/s-1",
      routes: routes({
        "GET /ingestion-runs": ({ query }) =>
          query.get("offset") === "2"
            ? page(
                [
                  ...older.slice(3),
                  run({
                    id: "r-new",
                    status: "failed",
                    error_message: "Feed answered 503.",
                    created_at: "2026-09-25T08:00:00Z",
                  }),
                ],
                { total: 12, limit: 10, offset: 2 },
              )
            : page(older, { total: 12, limit: 10 }),
      }),
    });

    const section = await ingestion();
    expect(await within(section).findByText("The newest 8 of 12 runs.")).toBeInTheDocument();
    const rows = within(section).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("failed");
    expect(rows[0]).toHaveTextContent("Feed answered 503.");
    expect(rows[0]).toHaveTextContent("2026-09-25 08:00 UTC");
    const runCalls = calls.filter((call) => call.path === "/ingestion-runs");
    expect(runCalls.map((call) => call.query.get("source_id"))).toEqual(["s-1", "s-1"]);
    expect(runCalls.every((call) => call.query.get("organization_id") === "org-a")).toBe(true);
  });

  it("queues a run once and shows it", async () => {
    const posted = [];
    const answer = held();
    let runs = [run()];
    renderApp({
      path: "/sources/s-1",
      routes: routes({
        "GET /ingestion-runs": () => page(runs),
        "POST /ingestion-runs": async (request) => {
          posted.push(request);
          await answer.ready;
          runs = [
            ...runs,
            run({ id: "r-2", status: "pending", started_at: null, finished_at: null }),
          ];
          return { status: 201, body: runs.at(-1) };
        },
      }),
    });
    const user = userEvent.setup();

    const section = await ingestion();
    await user.click(within(section).getByRole("button", { name: "Ingest now" }));
    const busy = within(section).getByRole("button", { name: "Queueing..." });
    expect(busy).toBeDisabled();
    await user.click(busy);
    answer.release();

    expect(
      await within(section).findByText("Ingestion was queued. A worker will run it."),
    ).toBeInTheDocument();
    expect(await within(section).findByText("pending")).toBeInTheDocument();
    expect(posted).toHaveLength(1);
    expect(posted[0].body).toEqual({ source_id: "s-1" });
    expect(posted[0].query.get("organization_id")).toBe("org-a");
  });

  it("polls active runs until they are completed", async () => {
    let request = 0;
    const { calls } = renderApp({
      path: "/sources/s-1",
      routes: routes({
        "GET /ingestion-runs": () => {
          const statuses = ["pending", "running", "completed"];
          const status = statuses[Math.min(request, statuses.length - 1)];
          request += 1;
          return page([
            run({
              status,
              started_at: status === "pending" ? null : "2026-09-05T07:01:00Z",
              finished_at: status === "completed" ? "2026-09-05T07:02:00Z" : null,
            }),
          ]);
        },
      }),
    });

    const section = await ingestion();
    await within(section).findByText("pending");
    vi.useFakeTimers();
    await vi.advanceTimersByTimeAsync(5000);
    expect(await within(section).findByText("running")).toBeInTheDocument();
    await vi.advanceTimersByTimeAsync(5000);
    expect(await within(section).findByText("completed")).toBeInTheDocument();
    const count = calls.filter((call) => call.path === "/ingestion-runs").length;
    await vi.advanceTimersByTimeAsync(10000);
    expect(calls.filter((call) => call.path === "/ingestion-runs")).toHaveLength(count);
  });

  it("keeps manual refresh available", async () => {
    const { calls } = renderApp({ path: "/sources/s-1", routes: routes() });
    const user = userEvent.setup();
    const section = await ingestion();
    await within(section).findByText("completed");

    await user.click(within(section).getByRole("button", { name: "Refresh runs" }));

    await waitFor(() =>
      expect(calls.filter((call) => call.path === "/ingestion-runs")).toHaveLength(2),
    );
  });

  it("shows a refused run", async () => {
    renderApp({
      path: "/sources/s-1",
      routes: routes({
        "POST /ingestion-runs": {
          status: 409,
          body: {
            error: { code: "conflict", message: "upload sources cannot be ingested by a worker." },
          },
        },
      }),
    });
    const user = userEvent.setup();

    const section = await ingestion();
    await user.click(within(section).getByRole("button", { name: "Ingest now" }));

    expect(await within(section).findByRole("alert")).toHaveTextContent(
      "upload sources cannot be ingested by a worker.",
    );
    expect(within(section).getByRole("button", { name: "Ingest now" })).toBeEnabled();
  });

  it("starts and pauses the schedule", async () => {
    const sent = [];
    renderApp({
      path: "/sources/s-1",
      routes: routes({
        "PUT /sources/s-1/schedule": ({ body }) => {
          sent.push(["PUT", body]);
          return {
            body: source({
              ingestion_enabled: true,
              ingestion_interval_minutes: body.interval_minutes,
              next_ingestion_at: "2026-10-01T10:00:00Z",
            }),
          };
        },
        "DELETE /sources/s-1/schedule": () => {
          sent.push(["DELETE"]);
          return { body: source({ ingestion_interval_minutes: 15 }) };
        },
      }),
    });
    const user = userEvent.setup();

    const section = await ingestion();
    const minutes = within(section).getByLabelText("Ingest every (minutes)");
    await user.clear(minutes);
    await user.type(minutes, "15");
    await user.click(within(section).getByRole("button", { name: "Start schedule" }));

    const config = screen.getByRole("region", { name: "Configuration" });
    expect(await within(config).findByText("Every 15 min")).toBeInTheDocument();
    await user.click(within(section).getByRole("button", { name: "Pause schedule" }));
    expect(await within(config).findByText("Paused")).toBeInTheDocument();
    expect(sent).toEqual([["PUT", { interval_minutes: 15 }], ["DELETE"]]);
  });

  it("only shows runs to viewers", async () => {
    renderApp({ path: "/sources/s-1", routes: routes({}, "viewer", USER) });

    const section = await ingestion();
    expect(await within(section).findByText("completed")).toBeInTheDocument();
    expect(within(section).queryByRole("button")).not.toBeInTheDocument();
  });

  it("explains that upload sources are not fetched", async () => {
    renderApp({
      path: "/sources/s-1",
      routes: routes({ "GET /sources/s-1": { body: source({ type: "upload", url: null }) } }),
    });

    const section = await ingestion();
    expect(
      within(section).getByText(/upload sources are not fetched by a worker/),
    ).toBeInTheDocument();
    expect(within(section).queryByRole("button", { name: "Ingest now" })).not.toBeInTheDocument();
  });

  it("drops the runs when switching organization", async () => {
    renderApp({ path: "/sources/s-1", routes: routes() });
    const user = userEvent.setup();

    await within(await ingestion()).findByText("completed");
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Ingestion" })).not.toBeInTheDocument(),
    );
    expect(await screen.findByText("Source was not found.")).toBeInTheDocument();
  });
});
