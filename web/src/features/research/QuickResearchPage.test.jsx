import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { held, page, researchEvidence, researchSession, source, turn } from "../../test/content.js";
import { signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

const EVIDENCE = [
  researchEvidence("E1", { chunk_metadata: { heading: "Findings" } }),
  researchEvidence("E2", { source_id: "s-2" }),
];

function routes(extra = {}) {
  return {
    ...signedIn(),
    ...organizations([HARBOUR, RIVER]),
    "GET /sources": page([source(), source({ id: "s-2", name: "Harbour Site" })]),
    "POST /research/context": ({ body }) => ({
      body: { query: body.query, mode: body.mode, evidence: EVIDENCE, context_text: "[E1] ..." },
    }),
    "POST /research/answer": ({ body }) => ({
      body: {
        query: body.query,
        mode: body.mode,
        answer: { text: "Storms closed it [E2].", citation_ids: ["E2"] },
        citations: [{ citation_id: "E2", ...EVIDENCE[1] }],
        evidence: EVIDENCE,
      },
    }),
    ...extra,
  };
}

async function ask(user, question, button, { mode, source } = {}) {
  const form = await screen.findByRole("form", { name: "Research question" });
  await within(form).findByRole("option", { name: "Harbour Site" });
  await user.type(within(form).getByLabelText("Question"), question);
  if (mode) await user.selectOptions(within(form).getByLabelText("Mode"), mode);
  if (source) await user.selectOptions(within(form).getByLabelText("Source"), source);
  await user.click(within(form).getByRole("button", { name: button }));
}

function researchCalls(calls) {
  return calls.filter((call) => call.path.startsWith("/research/"));
}

describe("quick research", () => {
  it("collects evidence only", async () => {
    const { calls } = renderApp({ path: "/research/new", routes: routes() });
    const user = userEvent.setup();

    await ask(user, "Why did the harbour close?", "Collect evidence");

    const evidence = await screen.findByRole("region", { name: "Evidence" });
    const cards = within(evidence).getAllByRole("listitem");
    expect(cards.map((card) => card.getAttribute("aria-label"))).toEqual([
      "Evidence E1",
      "Evidence E2",
    ]);
    expect(cards[0]).toHaveTextContent("Report E1");
    expect(cards[0]).toHaveTextContent("Excerpt of E1.");
    expect(cards[0]).toHaveTextContent("Section: Findings");
    expect(screen.queryByRole("region", { name: "Answer" })).not.toBeInTheDocument();
    const [call] = researchCalls(calls);
    expect(call.path).toBe("/research/context");
    expect(call.body).toEqual({
      query: "Why did the harbour close?",
      mode: "hybrid",
      limit: 8,
      organization_id: "org-a",
    });
  });

  it("starts a saved session and opens it", async () => {
    const started = [];
    const { calls } = renderApp({
      path: "/research/new",
      routes: routes({
        "POST /research/sessions/start": ({ body }) => {
          started.push(body);
          return {
            status: 201,
            body: { session: researchSession({ title: "Harbour" }), turn: turn(1) },
          };
        },
        "GET /research/sessions/rs-1": { body: researchSession({ title: "Harbour" }) },
        "GET /research/sessions/rs-1/turns": page([turn(1)]),
      }),
    });
    const user = userEvent.setup();

    await ask(user, "Why did the harbour close?", "Start research session", { mode: "lexical" });

    // The new session page opens.
    expect(await screen.findByRole("region", { name: "Conversation" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 1, name: "Harbour" })).toBeInTheDocument();
    // The server was asked to start the session; no answer or evidence was sent.
    expect(started).toEqual([
      {
        question: "Why did the harbour close?",
        retrieval_mode: "lexical",
        limit: 8,
        organization_id: "org-a",
      },
    ]);
    expect(researchCalls(calls).some((call) => call.path === "/research/context")).toBe(false);
  });

  it("answers with citations that lead to their evidence", async () => {
    renderApp({ path: "/research/new", routes: routes() });
    const user = userEvent.setup();

    await ask(user, "Why did the harbour close?", "Collect evidence and answer");

    const answer = await screen.findByRole("region", { name: "Answer" });
    expect(answer).toHaveTextContent("Storms closed it [E2].");
    expect(answer).toHaveTextContent("Cites 1 of 2 evidence pieces.");
    const evidence = screen.getByRole("region", { name: "Evidence" });
    expect(within(evidence).getByRole("listitem", { name: "Evidence E2" })).toHaveTextContent(
      "cited",
    );
    expect(within(evidence).getByRole("listitem", { name: "Evidence E1" })).not.toHaveTextContent(
      "cited",
    );
    await user.click(within(answer).getByRole("button", { name: "Show evidence E2" }));
    await waitFor(() =>
      expect(within(evidence).getByRole("listitem", { name: "Evidence E2" })).toHaveFocus(),
    );
  });

  it("sends the chosen mode and source", async () => {
    const { calls } = renderApp({ path: "/research/new", routes: routes() });
    const user = userEvent.setup();

    await ask(user, "Harbour?", "Collect evidence", { mode: "lexical", source: "s-2" });

    await screen.findByRole("region", { name: "Evidence" });
    const [call] = researchCalls(calls);
    expect(call.body.mode).toBe("lexical");
    expect(call.body.source_id).toBe("s-2");
  });

  it("explains a missing answer model", async () => {
    renderApp({
      path: "/research/new",
      routes: routes({
        "POST /research/answer": {
          status: 503,
          body: { error: { code: "service_unavailable", message: "Local answers are off." } },
        },
      }),
    });
    const user = userEvent.setup();

    await ask(user, "Harbour?", "Collect evidence and answer");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("No answer model is enabled on the server");
    expect(alert).toHaveTextContent("Local answers are off.");
  });

  it("says when no evidence was found", async () => {
    renderApp({
      path: "/research/new",
      routes: routes({
        "POST /research/answer": ({ body }) => ({
          body: { query: body.query, mode: body.mode, answer: null, citations: [], evidence: [] },
        }),
      }),
    });
    const user = userEvent.setup();

    await ask(user, "Nothing here?", "Collect evidence and answer");

    expect(
      await screen.findByText("No evidence was found, so no answer was written."),
    ).toBeInTheDocument();
    expect(screen.getByText("No evidence was found in this organization.")).toBeInTheDocument();
  });

  it("drops the result when switching organization", async () => {
    const river = held();
    renderApp({
      path: "/research/new",
      routes: routes({
        "GET /sources": async ({ query }) => {
          if (query.get("organization_id") === "org-b") await river.ready;
          return page([source(), source({ id: "s-2", name: "Harbour Site" })]);
        },
      }),
    });
    const user = userEvent.setup();

    await ask(user, "Harbour?", "Collect evidence");
    await screen.findByText("Excerpt of E1.");
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    await waitFor(() => expect(screen.queryByText("Excerpt of E1.")).not.toBeInTheDocument());
    expect(screen.getByLabelText("Question", { selector: "textarea" })).toHaveValue("");
    river.release();
  });
});
