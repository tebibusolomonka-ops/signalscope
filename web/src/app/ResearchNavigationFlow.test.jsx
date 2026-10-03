import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";

import {
  doc,
  documentChunk,
  entity,
  evidence,
  hit,
  page,
  researchEvidence,
  researchSession,
  source,
  turn,
} from "../test/content.js";
import { TOKEN, USER } from "../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../test/organizations.js";
import { renderApp } from "../test/renderApp.jsx";

const PASSWORD = "a long test password";

// Organization A content carries ALPHA markers; B carries BETA, so a leak shows.
const A_SOURCE = source({ id: "s-a", name: "Alpha Feed", organization_id: "org-a" });
const A_DOC = doc({
  id: "d-a",
  source_id: "s-a",
  title: "Alpha storm report",
  content: "Alpha body.",
});
const A_CHUNKS = [
  documentChunk(0, { chunk_id: "c-a0", text: "Alpha chunk zero." }),
  documentChunk(1, { chunk_id: "c-a1", text: "Alpha chunk one, the key passage." }),
];
const A_ENTITY = entity({ id: "e-a", canonical_name: "Alpha Authority" });
const A_SESSION = researchSession({
  id: "rs-a",
  title: "Alpha questions",
  organization_id: "org-a",
});

function hybridHit(organization) {
  return organization === "org-b"
    ? {
        body: {
          items: [
            hit({
              document_id: "d-b",
              chunk_id: "c-b1",
              title: "Beta result",
              excerpt: "Beta hit.",
            }),
          ],
        },
      }
    : {
        body: {
          items: [
            hit({
              document_id: "d-a",
              chunk_id: "c-a1",
              title: "Alpha storm report",
              excerpt: "Alpha hit.",
            }),
          ],
        },
      };
}

function byOrg(a, b) {
  return ({ query }) => (query.get("organization_id") === "org-b" ? b : a);
}

function routes() {
  return {
    "POST /auth/login": ({ body }) =>
      body.password === PASSWORD
        ? { body: { access_token: TOKEN, token_type: "bearer", expires_at: "x", user: USER } }
        : { status: 401, body: { error: { code: "unauthenticated", message: "No." } } },
    "POST /auth/logout": { status: 204 },
    ...organizations([HARBOUR, RIVER], "member"),
    "GET /sources": byOrg(
      page([A_SOURCE]),
      page([source({ id: "s-b", name: "Beta Feed", organization_id: "org-b" })]),
    ),
    "GET /investigations": byOrg(page([]), page([])),
    "GET /search/hybrid": ({ query }) => hybridHit(query.get("organization_id")),
    "GET /documents/d-a": byOrg(
      { body: A_DOC },
      { status: 404, body: { error: { code: "not_found", message: "Document was not found." } } },
    ),
    "GET /sources/s-a": { body: A_SOURCE },
    "GET /documents/d-a/revisions": { body: { items: [] } },
    "GET /documents/d-a/chunks": byOrg(page(A_CHUNKS), {
      status: 404,
      body: { error: { code: "not_found", message: "Document was not found." } },
    }),
    "GET /entities": byOrg(
      page([A_ENTITY]),
      page([entity({ id: "e-b", canonical_name: "Beta Council" })]),
    ),
    "GET /entities/e-a": byOrg(
      {
        body: {
          entity: A_ENTITY,
          mention_count: 1,
          mentions: [
            evidence({
              surface_text: "Alpha Authority",
              document_title: "Alpha storm report",
              source_name: "Alpha Feed",
            }),
          ],
        },
      },
      { status: 404, body: { error: { code: "not_found", message: "Entity was not found." } } },
    ),
    "GET /research/sessions": byOrg(page([A_SESSION]), page([])),
    "GET /research/sessions/rs-a": byOrg(
      { body: A_SESSION },
      { body: researchSession({ id: "rs-a", organization_id: "org-b" }) },
    ),
    "GET /research/sessions/rs-a/turns": byOrg(
      page([
        turn(1, {
          id: "t-a1",
          question: "What happened in Alpha?",
          answer: "Alpha harbour closed [E1].",
          citation_ids: ["E1"],
          evidence: [
            researchEvidence("E1", {
              document_id: "d-a",
              chunk_id: "c-a1",
              title: "Alpha storm report",
              excerpt: "Alpha evidence excerpt.",
            }),
          ],
        }),
      ]),
      page([]),
    ),
  };
}

async function go(user, label) {
  const nav = screen.getByRole("navigation", { name: "Main" });
  await user.click(within(nav).getByRole("link", { name: label }));
}

it("navigates evidence to the exact chunk and keeps organizations apart", async () => {
  renderApp({ path: "/login", routes: routes() });
  const user = userEvent.setup();

  // Sign in and select Organization A.
  await user.type(await screen.findByLabelText("Email"), "mel@example.org");
  await user.type(screen.getByLabelText("Password"), PASSWORD);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  await user.selectOptions(await screen.findByLabelText("Active organization"), "org-a");

  // Search, then open the result at its exact chunk.
  await go(user, "Search");
  await user.type(await screen.findByLabelText("Search for"), "alpha");
  await user.click(screen.getByRole("button", { name: "Search" }));
  const resultLink = await screen.findByRole("link", { name: "Alpha storm report" });
  expect(resultLink).toHaveAttribute("href", "/documents/d-a?chunk=c-a1");
  await user.click(resultLink);

  const focus = await screen.findByRole("region", { name: "Focused evidence" });
  expect(await within(focus).findByText("Alpha chunk one, the key passage.")).toBeInTheDocument();

  // Entity evidence.
  await go(user, "Entities");
  await user.click(await screen.findByRole("link", { name: "Alpha Authority" }));
  expect(await screen.findByRole("table", { name: "Mentions" })).toHaveTextContent(
    "Alpha storm report",
  );

  // Research session: follow a citation, then open the evidence in the document.
  await go(user, "Research");
  await user.click(await screen.findByRole("link", { name: "Alpha questions" }));
  const talk = await screen.findByRole("region", { name: "Conversation" });
  const [citation] = within(talk).getAllByRole("button", { name: "Show evidence E1" });
  await user.click(citation);
  const panel = screen.getByRole("region", { name: "Evidence" });
  const evidenceLink = within(panel).getByRole("link", { name: "Alpha storm report" });
  expect(evidenceLink).toHaveAttribute("href", "/documents/d-a?chunk=c-a1");
  await user.click(evidenceLink);
  expect(await screen.findByText("Alpha chunk one, the key passage.")).toBeInTheDocument();

  // Switch to Organization B: no Alpha sentinel may remain.
  await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");
  await waitFor(() => expect(screen.queryByText(/Alpha chunk one/)).not.toBeInTheDocument());
  await go(user, "Entities");
  expect(await screen.findByText("Beta Council")).toBeInTheDocument();
  expect(screen.queryByText("Alpha Authority")).not.toBeInTheDocument();
  expect(document.body.textContent).not.toContain("Alpha chunk");
  expect(document.body.innerHTML).not.toContain(TOKEN);
});
