import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { page } from "../../test/content.js";
import { ADMIN, USER, signedIn } from "../../test/fakeApi.js";
import { organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

function summary(overrides = {}) {
  return {
    id: "rep-1",
    task: "embedding_retrieval",
    model: "e5-small",
    provider: "sentence_transformers",
    dataset_name: "pilot",
    dataset_fingerprint: "abc123",
    report_version: 1,
    created_at: "2026-10-01T00:00:00Z",
    ...overrides,
  };
}

function detail(overrides = {}) {
  return {
    ...summary(),
    report_json: {
      metrics: { "recall@5": 0.8 },
      timings: { total_seconds: 1.2 },
      warnings: ["Small dataset."],
    },
    environment_summary: { python: "3.12" },
    ...overrides,
  };
}

function routes(extra = {}, user = ADMIN) {
  return {
    ...signedIn(user),
    ...organizations(),
    "GET /admin/evaluations": page([
      summary(),
      summary({ id: "rep-2", task: "relation_evaluation", model: "gliner2" }),
    ]),
    ...extra,
  };
}

describe("evaluation workspace", () => {
  it("lists reports for a system admin", async () => {
    const { calls } = renderApp({ path: "/evaluations", routes: routes() });

    expect(await screen.findByText("e5-small")).toBeInTheDocument();
    expect(screen.getByText("gliner2")).toBeInTheDocument();
    expect(calls.some((call) => call.path === "/admin/evaluations")).toBe(true);
  });

  it("filters by task", async () => {
    const { calls } = renderApp({ path: "/evaluations", routes: routes() });
    const user = userEvent.setup();

    await screen.findByText("e5-small");
    await user.selectOptions(screen.getByLabelText("Task"), "relation_evaluation");

    await waitFor(() =>
      expect(
        calls
          .filter((c) => c.path === "/admin/evaluations")
          .at(-1)
          .query.get("task"),
      ).toBe("relation_evaluation"),
    );
  });

  it("shows a report detail with metrics and a relation note", async () => {
    renderApp({
      path: "/evaluations",
      routes: routes({
        "GET /admin/evaluations/rep-2": {
          body: detail({
            id: "rep-2",
            task: "relation_evaluation",
            model: "gliner2",
            report_json: { metrics: { f1: 0.4 }, timings: {}, warnings: [] },
          }),
        },
      }),
    });
    const user = userEvent.setup();

    await screen.findByText("gliner2");
    const rows = screen.getAllByRole("row");
    const relationRow = rows.find((row) => within(row).queryByText("relation_evaluation"));
    await user.click(within(relationRow).getByRole("button", { name: "View" }));

    const panel = await screen.findByRole("region", { name: "Report detail" });
    expect(within(panel).getByText("f1")).toBeInTheDocument();
    expect(within(panel).getByText(/Relation persistence is not enabled/)).toBeInTheDocument();
  });

  it("imports a pasted report", async () => {
    let posted = null;
    renderApp({
      path: "/evaluations",
      routes: routes({
        "POST /admin/evaluations/import": ({ body }) => {
          posted = body;
          return { status: 201, body: detail({ model: "e5-base" }) };
        },
      }),
    });
    const user = userEvent.setup();

    const form = await screen.findByRole("region", { name: "Import a report" });
    await user.type(within(form).getByLabelText("Report JSON"), '{{"report_version":1}');
    await user.click(within(form).getByRole("button", { name: "Import report" }));

    expect(await within(form).findByRole("status")).toHaveTextContent("Stored report for e5-base");
    expect(posted).toEqual({ report: { report_version: 1 } });
  });

  it("compares selected reports and shows deltas, no winner", async () => {
    renderApp({
      path: "/evaluations",
      routes: routes({
        "POST /admin/evaluations/compare": {
          body: {
            task: "embedding_retrieval",
            dataset_fingerprint: "abc123",
            reports: ["rep-1", "rep-2"],
            metrics: { "recall@5": { values: [0.8, 0.9], deltas: [0, 0.1] } },
            timings: {},
          },
        },
      }),
    });
    const user = userEvent.setup();

    await screen.findByText("e5-small");
    await user.click(screen.getByRole("checkbox", { name: "Compare e5-small" }));
    await user.click(screen.getByRole("checkbox", { name: "Compare gliner2" }));

    const panel = await screen.findByRole("region", { name: "Comparison" });
    expect(within(panel).getByText("recall@5")).toBeInTheDocument();
    expect(panel).toHaveTextContent("+0.1");
    expect(panel).not.toHaveTextContent(/winner|better|recommend/i);
  });

  it("shows a comparison refusal cleanly", async () => {
    renderApp({
      path: "/evaluations",
      routes: routes({
        "POST /admin/evaluations/compare": {
          status: 422,
          body: {
            error: { code: "invalid_input", message: "Evaluation reports have different tasks." },
          },
        },
      }),
    });
    const user = userEvent.setup();

    await screen.findByText("e5-small");
    await user.click(screen.getByRole("checkbox", { name: "Compare e5-small" }));
    await user.click(screen.getByRole("checkbox", { name: "Compare gliner2" }));

    const panel = await screen.findByRole("region", { name: "Comparison" });
    expect(await within(panel).findByRole("alert")).toHaveTextContent("different tasks");
  });

  it("refuses non-admins", async () => {
    const { calls } = renderApp({ path: "/evaluations", routes: routes({}, USER) });

    expect(
      await screen.findByText("Only system admins can review evaluation reports."),
    ).toBeInTheDocument();
    expect(calls.some((call) => call.path === "/admin/evaluations")).toBe(false);
  });
});
