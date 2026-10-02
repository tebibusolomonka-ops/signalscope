import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import {
  doc,
  entity,
  evidence,
  hit,
  investigation,
  page,
  provenance,
  researchEvidence,
  researchSession,
  savedItem,
  source,
  turn,
} from "../test/content.js";
import { DASHBOARD_ROUTES } from "../test/dashboardRoutes.js";
import { captureDownloads } from "../test/downloads.js";
import { TOKEN, USER } from "../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../test/organizations.js";
import { renderApp } from "../test/renderApp.jsx";

const PASSWORD = "a long test password";
const RIVER_SOURCE = source({ id: "s-r", name: "River Feed", organization_id: "org-b" });
const RIVER_DOC = doc({ id: "d-r", source_id: "s-r", title: "Flood warning issued" });
const RIVER_ENTITY = entity({ id: "e-r", canonical_name: "River Council" });
const RIVER_CASE = investigation({ id: "inv-r", title: "Spring floods", organization_id: "org-b" });
const RIVER_SESSION = researchSession({
  id: "rs-r",
  title: "Flood questions",
  organization_id: "org-b",
});
const INVESTIGATION_MARKDOWN = "# Spring floods\n\n## Entities\n\n- River Council\n";

/** A tenant with its own content; every content call must name River Desk. */
function riverRoutes(state) {
  return {
    "POST /auth/login": ({ body }) =>
      body.password === PASSWORD
        ? { body: { access_token: TOKEN, token_type: "bearer", expires_at: "x", user: USER } }
        : { status: 401, body: { error: { code: "unauthenticated", message: "No." } } },
    "POST /auth/logout": { status: 204 },
    ...organizations([HARBOUR, RIVER], "member"),
    ...DASHBOARD_ROUTES,
    "GET /sources": page([RIVER_SOURCE]),
    "GET /sources/s-r": { body: RIVER_SOURCE },
    "GET /sources/s-r/provenance": { body: provenance({ source_id: "s-r" }) },
    "GET /ingestion-runs": page([]),
    "GET /documents": page([RIVER_DOC]),
    "GET /documents/d-r": { body: RIVER_DOC },
    "GET /documents/d-r/revisions": { body: { items: [] } },
    "GET /search/hybrid": {
      body: {
        items: [
          hit({
            document_id: "d-r",
            source_id: "s-r",
            title: "Flood warning issued",
            excerpt: "The river rose overnight.",
            lexical_rank: 1,
            vector_similarity: 0.8,
            hybrid_score: 0.03,
          }),
        ],
      },
    },
    "GET /entities": page([RIVER_ENTITY]),
    "GET /entities/e-r": {
      body: {
        entity: RIVER_ENTITY,
        mention_count: 1,
        mentions: [evidence({ document_id: "d-r", surface_text: "the River Council" })],
      },
    },
    "GET /investigations": page([RIVER_CASE]),
    "POST /investigations/inv-r/items": ({ body }) => {
      state.saved.push(body);
      return {
        status: 201,
        body: savedItem("entity", { canonical_name: "River Council", entity_type: "organization" }),
      };
    },
    "GET /investigations/inv-r": { body: RIVER_CASE },
    "GET /investigations/inv-r/items": () => ({
      body: state.saved.map(() =>
        savedItem("entity", { canonical_name: "River Council", entity_type: "organization" }),
      ),
    }),
    "GET /investigations/inv-r/members": { body: [] },
    "GET /organizations/org-b/members": { body: [] },
    "GET /investigations/inv-r/export": { body: INVESTIGATION_MARKDOWN, type: "text" },
    "GET /research/sessions": page([RIVER_SESSION]),
    "GET /research/sessions/rs-r": { body: RIVER_SESSION },
    "GET /research/sessions/rs-r/turns": page([
      turn(1, { id: "t-r1", question: "Where did it flood?" }),
    ]),
    "POST /research/sessions/rs-r/turns": ({ body }) => ({
      status: 201,
      body: {
        session: RIVER_SESSION,
        turn: turn(2, {
          id: "t-r2",
          question: body.question,
          answer: "Warnings went out at dawn [E1].",
          citation_ids: ["E1"],
          evidence: [researchEvidence("E1", { excerpt: "Sirens sounded at dawn." })],
        }),
      },
    }),
    "GET /research/sessions/rs-r/export": ({ query }) => ({
      body: { session: RIVER_SESSION, format: query.get("format") },
    }),
  };
}

let downloads;
afterEach(() => downloads?.restore());

async function go(user, label) {
  const nav = screen.getByRole("navigation", { name: "Main" });
  await user.click(within(nav).getByRole("link", { name: label }));
}

describe("tenant research workflow", () => {
  it("runs from sign in to exports inside one organization", async () => {
    downloads = captureDownloads();
    const state = { saved: [] };
    const { calls } = renderApp({ path: "/login", routes: riverRoutes(state) });
    const user = userEvent.setup();

    // Sign in and choose River Desk.
    await user.type(await screen.findByLabelText("Email"), "mel@example.org");
    await user.type(screen.getByLabelText("Password"), PASSWORD);
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.selectOptions(await screen.findByLabelText("Active organization"), "org-b");

    // Source, then document.
    await go(user, "Sources");
    await user.click(await screen.findByRole("link", { name: "River Feed" }));
    expect(await screen.findByRole("region", { name: "Provenance" })).toBeInTheDocument();
    await go(user, "Documents");
    await user.click(await screen.findByRole("link", { name: "Flood warning issued" }));
    expect(await screen.findByRole("region", { name: "Text" })).toBeInTheDocument();

    // Search.
    await go(user, "Search");
    await user.type(await screen.findByLabelText("Search for"), "flood");
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("The river rose overnight.")).toBeInTheDocument();

    // Entity, saved to an investigation.
    await go(user, "Entities");
    await user.click(await screen.findByRole("link", { name: "River Council" }));
    await user.click(await screen.findByRole("button", { name: "Save to investigation" }));
    const saveForm = await screen.findByRole("form", { name: "Save to investigation" });
    await within(saveForm).findByRole("option", { name: "Spring floods" });
    await user.click(within(saveForm).getByRole("button", { name: "Save" }));
    expect(await within(saveForm).findByRole("status")).toHaveTextContent("Spring floods");

    // Research session: follow-up question, citation, export.
    await go(user, "Research");
    await user.click(await screen.findByRole("link", { name: "Flood questions" }));
    const talk = await screen.findByRole("region", { name: "Conversation" });
    await user.type(within(talk).getByLabelText("Question"), "When were warnings sent?");
    await user.click(within(talk).getByRole("button", { name: "Ask" }));
    expect(await within(talk).findByText(/Warnings went out at dawn/)).toBeInTheDocument();
    const [cite] = within(talk).getAllByRole("button", { name: "Show evidence E1" }).slice(-1);
    await user.click(cite);
    await waitFor(() =>
      expect(screen.getByRole("listitem", { name: "Evidence E1" })).toHaveFocus(),
    );
    expect(screen.getByRole("listitem", { name: "Evidence E1" })).toHaveTextContent(
      "Sirens sounded at dawn.",
    );
    await user.click(screen.getByRole("button", { name: "Export JSON" }));
    await waitFor(() => expect(downloads.files).toHaveLength(1));

    // Investigation with the saved entity, exported as Markdown.
    await go(user, "Investigations");
    await user.click(await screen.findByRole("link", { name: "Spring floods" }));
    const items = await screen.findByRole("region", { name: "Saved items" });
    expect(await within(items).findByRole("link", { name: "River Council" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Export Markdown" }));
    await waitFor(() => expect(downloads.files).toHaveLength(2));

    expect(downloads.files.map((file) => file.name)).toEqual([
      "signalscope-research-session-rs-r.json",
      "signalscope-investigation-inv-r.md",
    ]);
    expect(await downloads.files[1].blob.text()).toBe(INVESTIGATION_MARKDOWN);
    expect(state.saved).toEqual([{ item_type: "entity", reference_id: "e-r" }]);
    // Every content call after choosing River Desk names River Desk.
    const content = calls.filter(
      (call) => call.query.has("organization_id") && !call.path.startsWith("/dashboard"),
    );
    expect(content.length).toBeGreaterThan(10);
    expect(content.every((call) => call.query.get("organization_id") === "org-b")).toBe(true);
    // The token stays out of URLs and the page.
    expect(calls.every((call) => !call.path.includes(TOKEN))).toBe(true);
    expect(document.body.innerHTML).not.toContain(TOKEN);
    expect(localStorage.length).toBe(0);
  });
});
