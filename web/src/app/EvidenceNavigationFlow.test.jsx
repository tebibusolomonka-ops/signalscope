import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";

import { doc, documentChunk, entity, evidence, hit, page, source } from "../test/content.js";
import { TOKEN, USER } from "../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../test/organizations.js";
import { renderApp } from "../test/renderApp.jsx";

const PASSWORD = "a long test password";
// A document with many chunks, to prove direct lookup does not scan pages.
const A_CHUNKS = Array.from({ length: 120 }, (_, index) =>
  documentChunk(index, { chunk_id: `c-a${index}`, text: `Alpha passage ${index}.` }),
);

function inA(body, message = "Not found.") {
  return ({ query }) =>
    query.get("organization_id") === "org-a"
      ? { body }
      : { status: 404, body: { error: { code: "not_found", message } } };
}

function contextRoutes() {
  const routes = {};
  A_CHUNKS.forEach((chunk, index) => {
    routes[`GET /documents/d-a/chunks/${chunk.chunk_id}/context`] = inA({
      previous: index > 0 ? A_CHUNKS[index - 1] : null,
      current: chunk,
      next: index < A_CHUNKS.length - 1 ? A_CHUNKS[index + 1] : null,
    });
  });
  return routes;
}

function routes() {
  return {
    "POST /auth/login": ({ body }) =>
      body.password === PASSWORD
        ? { body: { access_token: TOKEN, token_type: "bearer", expires_at: "x", user: USER } }
        : { status: 401, body: { error: { code: "unauthenticated", message: "No." } } },
    "POST /auth/logout": { status: 204 },
    ...organizations([HARBOUR, RIVER], "member"),
    "GET /sources": page([source({ id: "s-a", name: "Alpha Feed", organization_id: "org-a" })]),
    "GET /investigations": page([]),
    "GET /documents/d-a": inA(
      doc({ id: "d-a", source_id: "s-a", title: "Alpha report", content: "Alpha." }),
      "Document was not found.",
    ),
    "GET /sources/s-a": { body: source({ id: "s-a", name: "Alpha Feed" }) },
    "GET /documents/d-a/revisions": { body: { items: [] } },
    "GET /search": {
      body: {
        items: [
          hit({
            document_id: "d-a",
            chunk_id: "c-a90",
            title: "Alpha report",
            excerpt: "Alpha hit.",
          }),
        ],
      },
    },
    "GET /search/semantic": {
      body: {
        items: [
          hit({
            document_id: "d-a",
            chunk_id: "c-a77",
            title: "Alpha report",
            excerpt: "Alpha hit.",
            similarity: 0.8,
          }),
        ],
      },
    },
    "GET /entities": page([entity({ id: "e-a", canonical_name: "Alpha Authority" })]),
    "GET /entities/e-a": inA(
      {
        entity: entity({ id: "e-a", canonical_name: "Alpha Authority" }),
        mention_count: 1,
        mentions: [
          evidence({
            document_id: "d-a",
            chunk_id: "c-a64",
            document_title: "Alpha report",
            source_id: "s-a",
            source_name: "Alpha Feed",
            surface_text: "Alpha Authority",
          }),
        ],
      },
      "Entity was not found.",
    ),
    ...contextRoutes(),
  };
}

async function go(user, label) {
  await user.click(
    within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name: label }),
  );
}

async function signIn(user) {
  await user.type(await screen.findByLabelText("Email"), "mel@example.org");
  await user.type(screen.getByLabelText("Password"), PASSWORD);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  await user.selectOptions(await screen.findByLabelText("Active organization"), "org-a");
}

it("opens evidence at the exact chunk from search and entity, and steps passages", async () => {
  const { calls } = renderApp({ path: "/login", routes: routes() });
  const user = userEvent.setup();
  await signIn(user);

  // Lexical search to the exact late chunk.
  await go(user, "Search");
  await user.type(await screen.findByLabelText("Search for"), "alpha");
  await user.selectOptions(screen.getByLabelText("Mode"), "lexical");
  await user.click(screen.getByRole("button", { name: "Search" }));
  const result = await screen.findByRole("link", { name: "Alpha report" });
  expect(result).toHaveAttribute("href", "/documents/d-a?chunk=c-a90");
  await user.click(result);
  expect(await screen.findByText("Alpha passage 90.")).toBeInTheDocument();
  // Direct lookup only: no paged chunk scan.
  expect(calls.some((call) => call.path === "/documents/d-a/chunks")).toBe(false);

  // Step to the next passage.
  const panel = screen.getByRole("region", { name: "Focused evidence" });
  await user.click(within(panel).getByRole("button", { name: "Next passage" }));
  expect(await screen.findByText("Alpha passage 91.")).toBeInTheDocument();

  // Entity evidence links to its exact chunk.
  await go(user, "Entities");
  await user.click(await screen.findByRole("link", { name: "Alpha Authority" }));
  const mentions = await screen.findByRole("table", { name: "Mentions" });
  expect(within(mentions).getByRole("link", { name: "Alpha report" })).toHaveAttribute(
    "href",
    "/documents/d-a?chunk=c-a64",
  );
});
