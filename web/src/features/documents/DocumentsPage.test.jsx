import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { doc, held, page, source } from "../../test/content.js";
import { signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

function routes(extra = {}) {
  return {
    ...signedIn(),
    ...organizations([HARBOUR, RIVER]),
    "GET /sources": page([source(), source({ id: "s-2", name: "Harbour Site" })]),
    "GET /documents": page([doc()]),
    ...extra,
  };
}

function documentCalls(calls) {
  return calls.filter((call) => call.path === "/documents");
}

describe("documents workspace", () => {
  it("lists documents with their source and links", async () => {
    const { calls } = renderApp({ path: "/documents", routes: routes() });

    const title = await screen.findByRole("link", { name: "Storm closes the harbour" });
    expect(title).toHaveAttribute("href", "/documents/d-1");
    const row = title.closest("tr");
    expect(await within(row).findByRole("link", { name: "Harbour Feed" })).toHaveAttribute(
      "href",
      "/sources/s-1",
    );
    expect(row).toHaveTextContent("2026-09-05 06:00 UTC");
    expect(row).toHaveTextContent("en");
    expect(documentCalls(calls)[0].query.get("organization_id")).toBe("org-a");
  });

  it("says when nothing matches", async () => {
    renderApp({ path: "/documents", routes: routes({ "GET /documents": page([]) }) });
    expect(await screen.findByText("No documents match.")).toBeInTheDocument();
  });

  it("pages with the API", async () => {
    const { calls } = renderApp({
      path: "/documents",
      routes: routes({
        "GET /documents": ({ query }) =>
          query.get("offset") === "50"
            ? page([doc({ id: "d-51", title: "Second page" })], { total: 51, offset: 50 })
            : page([doc()], { total: 51 }),
      }),
    });
    const user = userEvent.setup();

    expect(await screen.findByText("Showing 1 to 1 of 51")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next page" }));

    expect(await screen.findByText("Second page")).toBeInTheDocument();
    expect(screen.getByText("Showing 51 to 51 of 51")).toBeInTheDocument();
    expect(documentCalls(calls).at(-1).query.get("offset")).toBe("50");
  });

  it("filters by source, language and published days", async () => {
    const { calls } = renderApp({ path: "/documents", routes: routes() });
    const user = userEvent.setup();

    const form = await screen.findByRole("search", { name: "Filter documents" });
    await within(form).findByRole("option", { name: "Harbour Site" });
    await user.selectOptions(within(form).getByLabelText("Source"), "s-2");
    await user.type(within(form).getByLabelText("Language"), "de");
    await user.type(within(form).getByLabelText("Published from (UTC)"), "2026-09-01");
    await user.type(within(form).getByLabelText("Published to (UTC)"), "2026-09-30");
    await user.click(within(form).getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(documentCalls(calls).at(-1).query.get("source_id")).toBe("s-2"));
    const query = documentCalls(calls).at(-1).query;
    expect(query.get("language")).toBe("de");
    expect(query.get("published_from")).toBe("2026-09-01T00:00:00Z");
    expect(query.get("published_to")).toBe("2026-09-30T23:59:59.999Z");
    expect(query.get("organization_id")).toBe("org-a");
  });

  it("shows loading and then an API error", async () => {
    const answer = held();
    renderApp({
      path: "/documents",
      routes: routes({
        "GET /documents": async () => {
          await answer.ready;
          return {
            status: 422,
            body: { error: { code: "validation_error", message: "Invalid language." } },
          };
        },
      }),
    });

    expect(await screen.findByText("Loading...")).toBeInTheDocument();
    answer.release();
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid language.");
  });

  it("never shows the old organization's rows after switching", async () => {
    const river = held();
    renderApp({
      path: "/documents",
      routes: routes({
        "GET /documents": async ({ query }) => {
          if (query.get("organization_id") === "org-b") {
            await river.ready;
            return page([doc({ id: "d-b", title: "River flood report", source_id: "s-b" })]);
          }
          return page([doc()]);
        },
      }),
    });
    const user = userEvent.setup();

    await screen.findByText("Storm closes the harbour");
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    await waitFor(() =>
      expect(screen.queryByText("Storm closes the harbour")).not.toBeInTheDocument(),
    );
    river.release();
    expect(await screen.findByText("River flood report")).toBeInTheDocument();
    expect(screen.queryByText("Storm closes the harbour")).not.toBeInTheDocument();
  });
});
