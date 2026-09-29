import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import {
  forbidden,
  held,
  page,
  researchEvidence,
  researchSession,
  source,
  turn,
} from "../../test/content.js";
import { USER, signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

function routes(turns, extra = {}, role = "member") {
  return {
    ...signedIn(USER),
    ...organizations([HARBOUR, RIVER], role),
    "GET /sources": page([source()]),
    "GET /research/sessions/rs-1": { body: researchSession() },
    "GET /research/sessions/rs-1/turns": { body: turns },
    ...extra,
  };
}

async function conversation() {
  return screen.findByRole("region", { name: "Conversation" });
}

describe("multi turn research", () => {
  it("shows the turns, the answer and the latest turn's evidence apart", async () => {
    renderApp({ path: "/research/rs-1", routes: routes([turn(1)]) });

    const talk = await conversation();
    expect(within(talk).getByText("Question number 1?")).toBeInTheDocument();
    expect(within(talk).getByText(/The harbour closed/)).toBeInTheDocument();
    expect(within(talk).queryByText("Excerpt of E1.")).not.toBeInTheDocument();
    const evidence = screen.getByRole("region", { name: "Evidence" });
    const cards = within(evidence).getAllByRole("listitem");
    expect(cards.map((card) => card.getAttribute("aria-label"))).toEqual([
      "Evidence E1",
      "Evidence E2",
    ]);
    expect(cards[0]).toHaveTextContent("cited");
    expect(cards[1]).not.toHaveTextContent("cited");
    expect(within(cards[0]).getByRole("link", { name: "Report E1" })).toHaveAttribute(
      "href",
      "/documents/d-E1",
    );
    expect(await within(cards[0]).findByRole("link", { name: "Harbour Feed" })).toHaveAttribute(
      "href",
      "/sources/s-1",
    );
    expect(within(evidence).queryByText(/The harbour closed/)).not.toBeInTheDocument();
  });

  it("moves focus to the cited evidence", async () => {
    renderApp({ path: "/research/rs-1", routes: routes([turn(1)]) });
    const user = userEvent.setup();

    const talk = await conversation();
    const [inline] = within(talk).getAllByRole("button", { name: "Show evidence E1" });
    await user.click(inline);

    await waitFor(() =>
      expect(screen.getByRole("listitem", { name: "Evidence E1" })).toHaveFocus(),
    );
  });

  it("says when evidence was collected without an answer model", async () => {
    renderApp({
      path: "/research/rs-1",
      routes: routes([turn(1, { answer: null, citation_ids: [], citations: [] })]),
    });

    const talk = await conversation();
    expect(
      within(talk).getByText(
        "Evidence collected; no answer model is configured, so no answer was written.",
      ),
    ).toBeInTheDocument();
  });

  it("asks a follow-up, shows it pending, then its answer and evidence", async () => {
    const answer = held();
    let posted = null;
    renderApp({
      path: "/research/rs-1",
      routes: routes([turn(1)], {
        "POST /research/sessions/rs-1/turns": async ({ body }) => {
          posted = body;
          await answer.ready;
          return {
            status: 201,
            body: {
              session: researchSession(),
              turn: turn(2, {
                question: body.question,
                answer: "It reopened later [E3].",
                citation_ids: ["E3"],
                evidence: [researchEvidence("E3")],
              }),
            },
          };
        },
      }),
    });
    const user = userEvent.setup();

    const talk = await conversation();
    const form = within(talk).getByRole("form", { name: "Ask a question" });
    await user.type(within(form).getByLabelText("Question"), "When did it reopen?");
    await user.clear(within(form).getByLabelText("Evidence pieces"));
    await user.type(within(form).getByLabelText("Evidence pieces"), "5");
    await user.click(within(form).getByRole("button", { name: "Ask" }));

    expect(await within(talk).findByText("Searching and answering...")).toBeInTheDocument();
    expect(within(form).getByRole("button", { name: "Asking..." })).toBeDisabled();
    answer.release();

    expect(await within(talk).findByText(/It reopened later/)).toBeInTheDocument();
    expect(within(talk).queryByText("Searching and answering...")).not.toBeInTheDocument();
    const evidence = screen.getByRole("region", { name: "Evidence" });
    expect(within(evidence).getByRole("listitem", { name: "Evidence E3" })).toBeInTheDocument();
    expect(posted).toEqual({ question: "When did it reopen?", limit: 5 });
  });

  it("shows an earlier turn's evidence on request", async () => {
    renderApp({
      path: "/research/rs-1",
      routes: routes([
        turn(1, { evidence: [researchEvidence("E1", { excerpt: "First turn evidence." })] }),
        turn(2),
      ]),
    });
    const user = userEvent.setup();

    const talk = await conversation();
    const [first] = within(talk).getAllByRole("button", { name: /Show evidence \(/ });
    await user.click(first);

    const evidence = screen.getByRole("region", { name: "Evidence" });
    expect(within(evidence).getByText("First turn evidence.")).toBeInTheDocument();
  });

  it("shows a refused question", async () => {
    renderApp({
      path: "/research/rs-1",
      routes: routes([], {
        "POST /research/sessions/rs-1/turns": forbidden("You need the member role."),
      }),
    });
    const user = userEvent.setup();

    const talk = await conversation();
    await user.type(within(talk).getByLabelText("Question"), "Anything?");
    await user.click(within(talk).getByRole("button", { name: "Ask" }));

    expect(await within(talk).findByRole("alert")).toHaveTextContent("You need the member role.");
    expect(within(talk).getByLabelText("Question")).toHaveValue("Anything?");
  });

  it("lets viewers read without asking", async () => {
    renderApp({ path: "/research/rs-1", routes: routes([turn(1)], {}, "viewer") });

    const talk = await conversation();
    expect(within(talk).queryByRole("form", { name: "Ask a question" })).not.toBeInTheDocument();
  });

  it("does not keep the session after switching organization", async () => {
    renderApp({ path: "/research/rs-1", routes: routes([turn(1)]) });
    const user = userEvent.setup();

    await conversation();
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "does not belong to the active organization",
    );
    expect(screen.queryByText("Question number 1?")).not.toBeInTheDocument();
    expect(screen.queryByText("Excerpt of E1.")).not.toBeInTheDocument();
  });
});
