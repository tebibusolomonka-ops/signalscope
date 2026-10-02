import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { held, operationsJob, operationsOverview, page } from "../../test/content.js";
import { signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

function routes(extra = {}) {
  return {
    ...signedIn(),
    ...organizations([HARBOUR, RIVER], "owner"),
    "GET /operations/overview": { body: operationsOverview() },
    "GET /operations/jobs": page([
      operationsJob({ queue: "embedding", job_id: "job-1", error: "Model is not available." }),
      operationsJob({
        queue: "ingestion",
        job_id: "job-2",
        resource_type: "source",
        error: "Feed 503.",
      }),
    ]),
    ...extra,
  };
}

function jobCalls(calls) {
  return calls.filter((call) => call.path === "/operations/jobs");
}

describe("failed job recovery", () => {
  it("lists failed jobs with their safe error", async () => {
    const { calls } = renderApp({ path: "/operations", routes: routes() });

    const section = await screen.findByRole("region", { name: "Failed jobs" });
    const row = (await within(section).findByText("Model is not available.")).closest("tr");
    expect(row).toHaveTextContent("Embedding");
    expect(row).toHaveTextContent("chunk chunk-1");
    expect(row).toHaveTextContent("2");
    const call = jobCalls(calls)[0];
    expect(call.query.get("status")).toBe("failed");
    expect(call.query.get("organization_id")).toBe("org-a");
  });

  it("filters by queue", async () => {
    const { calls } = renderApp({ path: "/operations", routes: routes() });
    const user = userEvent.setup();

    const section = await screen.findByRole("region", { name: "Failed jobs" });
    await within(section).findByText("Model is not available.");
    await user.selectOptions(within(section).getByLabelText("Queue"), "embedding");

    await waitFor(() => expect(jobCalls(calls).at(-1).query.get("queue")).toBe("embedding"));
    expect(jobCalls(calls).at(-1).query.get("offset")).toBe("0");
  });

  it("pages failed jobs", async () => {
    const { calls } = renderApp({
      path: "/operations",
      routes: routes({
        "GET /operations/jobs": ({ query }) =>
          query.get("offset") === "20"
            ? page([operationsJob({ job_id: "late", error: "Second page error." })], {
                total: 21,
                offset: 20,
              })
            : page([operationsJob()], { total: 21 }),
      }),
    });
    const user = userEvent.setup();

    const section = await screen.findByRole("region", { name: "Failed jobs" });
    await within(section).findByText("Model is not available.");
    await user.click(within(section).getByRole("button", { name: "Next page" }));

    expect(await within(section).findByText("Second page error.")).toBeInTheDocument();
    expect(jobCalls(calls).at(-1).query.get("offset")).toBe("20");
  });

  it("retries a job after confirmation and reloads", async () => {
    const retries = [];
    let jobs = [
      operationsJob({ queue: "embedding", job_id: "job-1", error: "Model is not available." }),
    ];
    renderApp({
      path: "/operations",
      routes: routes({
        "GET /operations/jobs": () => page(jobs),
        "POST /operations/jobs/embedding/job-1/retry": (request) => {
          retries.push(request);
          jobs = [];
          return { body: operationsJob({ job_id: "job-1", status: "pending", error: null }) };
        },
      }),
    });
    const user = userEvent.setup();

    const section = await screen.findByRole("region", { name: "Failed jobs" });
    const row = (await within(section).findByText("Model is not available.")).closest("tr");
    await user.click(within(row).getByRole("button", { name: "Retry" }));
    await user.click(within(row).getByRole("button", { name: "Yes, retry" }));

    await waitFor(() =>
      expect(within(section).queryByText("Model is not available.")).not.toBeInTheDocument(),
    );
    expect(await within(section).findByText("No failed jobs.")).toBeInTheDocument();
    expect(retries).toHaveLength(1);
    expect(retries[0].body).toEqual({ organization_id: "org-a" });
  });

  it("shows a not-retryable refusal without a traceback", async () => {
    renderApp({
      path: "/operations",
      routes: routes({
        "POST /operations/jobs/embedding/job-1/retry": {
          status: 409,
          body: {
            error: {
              code: "conflict",
              message:
                "The chunk already has current results from this model, so nothing is retried.",
            },
          },
        },
      }),
    });
    const user = userEvent.setup();

    const section = await screen.findByRole("region", { name: "Failed jobs" });
    const row = (await within(section).findByText("Model is not available.")).closest("tr");
    await user.click(within(row).getByRole("button", { name: "Retry" }));
    await user.click(within(row).getByRole("button", { name: "Yes, retry" }));

    expect(await within(row).findByRole("alert")).toHaveTextContent(
      "The chunk already has current results",
    );
    expect(within(row).getByText("Model is not available.")).toBeInTheDocument();
  });

  it("drops failed jobs of the old organization when switching", async () => {
    const river = held();
    renderApp({
      path: "/operations",
      routes: routes({
        "GET /operations/jobs": async ({ query }) => {
          if (query.get("organization_id") === "org-b") {
            await river.ready;
            return page([operationsJob({ job_id: "river-job", error: "River error." })]);
          }
          return page([operationsJob({ error: "Harbour error." })]);
        },
      }),
    });
    const user = userEvent.setup();

    await screen.findByText("Harbour error.");
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    await waitFor(() => expect(screen.queryByText("Harbour error.")).not.toBeInTheDocument());
    river.release();
    expect(await screen.findByText("River error.")).toBeInTheDocument();
  });
});
