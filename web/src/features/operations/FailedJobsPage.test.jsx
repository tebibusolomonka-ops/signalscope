import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { page } from "../../test/content.js";
import { USER, signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

function failedJob(overrides = {}) {
  return {
    queue: "claim_extraction",
    job_id: "job-1",
    status: "failed",
    resource_type: "chunk",
    resource_id: "c-1",
    provider: "test",
    model: "m",
    attempt_count: 3,
    available_at: "2026-09-20T08:00:00Z",
    created_at: "2026-09-20T08:00:00Z",
    finished_at: "2026-09-21T08:00:00Z",
    error: "Model is not available.",
    ...overrides,
  };
}

function routes(extra = {}, role = "owner", user) {
  return {
    ...signedIn(user),
    ...organizations([HARBOUR, RIVER], role),
    "GET /operations/jobs": page([failedJob()]),
    ...extra,
  };
}

describe("failed jobs page", () => {
  it("shows failed jobs with the short error only", async () => {
    renderApp({ path: "/operations/failed-jobs", routes: routes() });

    const section = await screen.findByRole("region", { name: "Failed jobs" });
    await within(section).findByText("Claim extraction");
    const row = within(section).getAllByRole("row")[1];
    expect(row).toHaveTextContent("Claim extraction");
    expect(row).toHaveTextContent("test/m");
    expect(row).toHaveTextContent("Model is not available.");
    expect(row).toHaveTextContent("2026-09-21 08:00 UTC");
  });

  it("filters by queue", async () => {
    const { calls } = renderApp({ path: "/operations/failed-jobs", routes: routes() });
    const user = userEvent.setup();

    const section = await screen.findByRole("region", { name: "Failed jobs" });
    await user.selectOptions(within(section).getByLabelText("Queue"), "embedding");

    await waitFor(() => {
      const last = calls.filter((call) => call.path === "/operations/jobs").at(-1);
      expect(last.query.get("queue")).toBe("embedding");
    });
  });

  it("retries a job after confirming and reloads", async () => {
    const posted = [];
    let jobs = [failedJob()];
    renderApp({
      path: "/operations/failed-jobs",
      routes: routes({
        "GET /operations/jobs": () => page(jobs),
        "POST /operations/jobs/retry": (request) => {
          posted.push(request.body);
          jobs = [];
          return { body: { queue: "claim_extraction", job_id: "job-1", status: "pending" } };
        },
      }),
    });
    const user = userEvent.setup();

    const section = await screen.findByRole("region", { name: "Failed jobs" });
    await user.click(await within(section).findByRole("button", { name: "Retry" }));
    await user.click(within(section).getByRole("button", { name: "Retry job" }));

    expect(await within(section).findByText("No failed jobs.")).toBeInTheDocument();
    expect(posted).toEqual([{ queue: "claim_extraction", job_id: "job-1" }]);
  });

  it("shows a refused retry", async () => {
    renderApp({
      path: "/operations/failed-jobs",
      routes: routes({
        "POST /operations/jobs/retry": {
          status: 409,
          body: { error: { code: "conflict", message: "Only a failed job can be retried." } },
        },
      }),
    });
    const user = userEvent.setup();

    const section = await screen.findByRole("region", { name: "Failed jobs" });
    await user.click(await within(section).findByRole("button", { name: "Retry" }));
    await user.click(within(section).getByRole("button", { name: "Retry job" }));

    expect(await within(section).findByRole("alert")).toHaveTextContent(
      "Only a failed job can be retried.",
    );
  });

  it("is not shown to members", async () => {
    renderApp({ path: "/operations/failed-jobs", routes: routes({}, "member", USER) });

    expect(
      await screen.findByText("Failed jobs are for organization owners and admins."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Failed jobs" })).not.toBeInTheDocument();
  });
});
