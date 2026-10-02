import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import {
  entity,
  held,
  hit,
  investigation,
  page,
  researchSession,
  source,
  turn,
} from "../test/content.js";
import { signedIn } from "../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../test/organizations.js";
import { renderApp } from "../test/renderApp.jsx";

function claim(id, text) {
  return {
    id,
    text,
    normalized_text: text.toLowerCase(),
    claim_type: "statistic",
    evidence_count: 1,
    created_at: "2026-09-05T07:00:00Z",
  };
}

function cluster(id, title) {
  return {
    cluster_id: id,
    event_type: "storm",
    title,
    occurred_at: null,
    event_count: 1,
    source_count: 1,
    evidence_count: 1,
    sources: [],
  };
}

/** Answers per organization; River Desk's answers wait until released. */
function tenantRoutes(river) {
  const both =
    (harbour, riverAnswer) =>
    async ({ query }) => {
      if (query.get("organization_id") === "org-b") {
        await river.ready;
        return riverAnswer;
      }
      return harbour;
    };
  return {
    ...signedIn(),
    ...organizations([HARBOUR, RIVER]),
    "GET /sources": both(page([source()]), page([])),
    "GET /search/hybrid": both(
      { body: { items: [hit({ title: "Harbour only result" })] } },
      {
        body: { items: [] },
      },
    ),
    "GET /entities": both(
      page([entity({ canonical_name: "Harbour only entity" })]),
      page([entity({ id: "e-b", canonical_name: "River entity" })]),
    ),
    "GET /claims": both(
      page([claim("k-a", "Harbour only claim")]),
      page([claim("k-b", "River claim")]),
    ),
    "GET /timeline": both(
      page([cluster("cl-a", "Harbour only event")]),
      page([cluster("cl-b", "River event")]),
    ),
    "GET /investigations": both(
      page([investigation({ title: "Harbour only investigation" })]),
      page([
        investigation({ id: "inv-b", title: "River investigation", organization_id: "org-b" }),
      ]),
    ),
    "GET /research/sessions/rs-1": both(
      { body: researchSession() },
      { body: researchSession({ organization_id: "org-a" }) },
    ),
    "GET /research/sessions/rs-1/turns": {
      body: page([turn(1, { question: "Harbour only research question?" })]).body,
    },
  };
}

async function searchHarbour(user) {
  await user.type(await screen.findByLabelText("Search for"), "harbour");
  await user.click(screen.getByRole("button", { name: "Search" }));
}

describe("switching organization", () => {
  it.each([
    ["/search", "Harbour only result", null, searchHarbour],
    ["/entities", "Harbour only entity", "River entity"],
    ["/claims", "Harbour only claim", "River claim"],
    ["/events", "Harbour only event", "River event"],
    ["/investigations", "Harbour only investigation", "River investigation"],
    ["/research/rs-1", "Harbour only research question?", null],
  ])("never shows Harbour content on %s as River Desk", async (path, harbour, riverText, act) => {
    const river = held();
    renderApp({ path, routes: tenantRoutes(river) });
    const user = userEvent.setup();

    if (act) await act(user);
    expect(await screen.findByText(harbour)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    // River's answers are held back: nothing of Harbour may fill the gap.
    await waitFor(() => expect(screen.queryByText(harbour)).not.toBeInTheDocument());
    river.release();
    if (riverText) expect(await screen.findByText(riverText)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Active organization")).toHaveValue("org-b"));
    expect(screen.queryByText(harbour)).not.toBeInTheDocument();
  });
});
