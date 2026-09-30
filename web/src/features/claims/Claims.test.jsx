import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { evidence, held, notFound, page } from "../../test/content.js";
import { signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

const VERDICTS = /\b(true|false|misinformation|credible|unreliable|verified|debunked)\b/i;

function claim(overrides = {}) {
  return {
    id: "k-1",
    text: "Harbour traffic fell by 40 percent",
    normalized_text: "harbour traffic fell by 40 percent",
    claim_type: "statistic",
    evidence_count: 2,
    created_at: "2026-09-05T07:00:00Z",
    ...overrides,
  };
}

function routes(extra = {}) {
  return {
    ...signedIn(),
    ...organizations([HARBOUR, RIVER]),
    "GET /claims": page([claim()]),
    "GET /claims/k-1": ({ query }) =>
      query.get("organization_id") === "org-a"
        ? {
            body: {
              claim: claim(),
              evidence_count: 2,
              evidence: [
                evidence({
                  id: "ev-1",
                  surface_text: "traffic fell by 40 percent",
                  provider: "gliner2",
                  model: "fastino/gliner2.5-multi-v1",
                }),
                evidence({ id: "ev-2", document_id: "d-2", confidence: null }),
              ],
            },
          }
        : notFound("Claim was not found."),
    ...extra,
  };
}

function claimCalls(calls) {
  return calls.filter((call) => call.path === "/claims");
}

describe("claim workspace", () => {
  it("lists claims with type and evidence count, without verdicts", async () => {
    const { calls } = renderApp({ path: "/claims", routes: routes() });

    const link = await screen.findByRole("link", { name: "Harbour traffic fell by 40 percent" });
    expect(link).toHaveAttribute("href", "/claims/k-1");
    expect(link.closest("tr")).toHaveTextContent("statistic");
    expect(link.closest("tr")).toHaveTextContent("2");
    expect(screen.getByRole("main")).not.toHaveTextContent(VERDICTS);
    expect(claimCalls(calls)[0].query.get("organization_id")).toBe("org-a");
  });

  it("filters by text and type", async () => {
    const { calls } = renderApp({ path: "/claims", routes: routes() });
    const user = userEvent.setup();

    const form = await screen.findByRole("search", { name: "Filter claims" });
    await user.type(within(form).getByLabelText("Text contains"), "traffic");
    await user.type(within(form).getByLabelText("Type"), "statistic");
    await user.click(within(form).getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(claimCalls(calls).at(-1).query.get("query")).toBe("traffic"));
    expect(claimCalls(calls).at(-1).query.get("claim_type")).toBe("statistic");
  });

  it("shows a claim's evidence with document links and no verdict", async () => {
    renderApp({ path: "/claims/k-1", routes: routes() });

    const statement = await screen.findByRole("region", { name: "Statement" });
    expect(statement).toHaveTextContent("Harbour traffic fell by 40 percent");
    const table = screen.getByRole("table", { name: "Evidence" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("traffic fell by 40 percent");
    expect(rows[0]).toHaveTextContent("gliner2 / fastino/gliner2.5-multi-v1");
    expect(rows[0]).toHaveTextContent("10 to 31");
    expect(within(rows[1]).getByRole("link", { name: "Storm closes the harbour" })).toHaveAttribute(
      "href",
      "/documents/d-2",
    );
    expect(within(rows[1]).getByRole("link", { name: "Harbour Feed" })).toHaveAttribute(
      "href",
      "/sources/s-1",
    );
    expect(rows[1]).toHaveTextContent("-");
    expect(screen.getByRole("main")).not.toHaveTextContent(VERDICTS);
  });

  it("shows an unknown claim", async () => {
    renderApp({ path: "/claims/k-9", routes: routes() });
    expect(await screen.findByRole("alert")).toHaveTextContent("Not found.");
  });

  it("drops the old organization's claims when switching", async () => {
    const river = held();
    renderApp({
      path: "/claims",
      routes: routes({
        "GET /claims": async ({ query }) => {
          if (query.get("organization_id") === "org-b") {
            await river.ready;
            return page([claim({ id: "k-b", text: "River levels rose" })]);
          }
          return page([claim()]);
        },
      }),
    });
    const user = userEvent.setup();

    await screen.findByText("Harbour traffic fell by 40 percent");
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    await waitFor(() =>
      expect(screen.queryByText("Harbour traffic fell by 40 percent")).not.toBeInTheDocument(),
    );
    river.release();
    expect(await screen.findByText("River levels rose")).toBeInTheDocument();
  });

  it("does not keep a claim after switching organization", async () => {
    renderApp({ path: "/claims/k-1", routes: routes() });
    const user = userEvent.setup();

    await screen.findByRole("table", { name: "Evidence" });
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    expect(await screen.findByText("Claim was not found.")).toBeInTheDocument();
    expect(screen.queryByText("traffic fell by 40 percent")).not.toBeInTheDocument();
  });
});
