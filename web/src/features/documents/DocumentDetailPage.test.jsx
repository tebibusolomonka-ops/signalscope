import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { doc, forbidden, notFound, page, revision, source } from "../../test/content.js";
import { USER, signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

function inHarbour(body, message) {
  return ({ query }) => (query.get("organization_id") === "org-a" ? { body } : notFound(message));
}

function routes(extra = {}, role = "owner", user) {
  return {
    ...signedIn(user),
    ...organizations([HARBOUR, RIVER], role),
    "GET /documents": page([doc()]),
    "GET /documents/d-1": inHarbour(doc(), "Document was not found."),
    "GET /sources/s-1": inHarbour(source(), "Source was not found."),
    "GET /documents/d-1/revisions": {
      body: { items: [revision(1), revision(2, { title: "Harbour shut" })] },
    },
    "GET /documents/d-1/revisions/1": {
      body: {
        document_id: "d-1",
        version: 1,
        title: "First title",
        content: "Early text of the storm story.",
        language: "en",
        url: null,
        content_hash: "abc",
        parser_metadata: { page_count: 3 },
        created_at: "2026-09-01T07:00:00Z",
      },
    },
    ...extra,
  };
}

describe("document detail", () => {
  it("shows the metadata, the source link and the text", async () => {
    renderApp({ path: "/documents/d-1", routes: routes() });

    expect(
      await screen.findByRole("heading", { level: 1, name: "Storm closes the harbour" }),
    ).toBeInTheDocument();
    const details = screen.getByRole("region", { name: "Details" });
    expect(within(details).getByRole("link", { name: "Harbour Feed" })).toHaveAttribute(
      "href",
      "/sources/s-1",
    );
    const url = within(details).getByRole("link", { name: "https://harbour.example/storm" });
    expect(url).toHaveAttribute("rel", "noopener noreferrer");
    expect(within(details).getByText("27 characters")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Text" })).toHaveTextContent(
      "The harbour closed at noon.",
    );
  });

  it("does not link a URL that is not http", async () => {
    renderApp({
      path: "/documents/d-1",
      routes: routes({ "GET /documents/d-1": { body: doc({ url: "javascript:alert(1)" }) } }),
    });

    const details = await screen.findByRole("region", { name: "Details" });
    expect(within(details).getByText("javascript:alert(1)").tagName).not.toBe("A");
  });

  it("lists revisions and opens one", async () => {
    renderApp({ path: "/documents/d-1", routes: routes() });
    const user = userEvent.setup();

    const revisions = await screen.findByRole("region", { name: "Revisions" });
    expect(await within(revisions).findByText("Harbour shut")).toBeInTheDocument();
    expect(within(revisions).getAllByText("abcdef012345")).toHaveLength(2);
    await user.click(within(revisions).getByRole("button", { name: "Version 1" }));

    const version = await screen.findByRole("article", { name: "Version 1" });
    expect(await within(version).findByText("Early text of the storm story.")).toBeInTheDocument();
    expect(within(version).getByText("Parser: page_count").nextElementSibling).toHaveTextContent(
      "3",
    );
    expect(within(revisions).getByRole("button", { name: "Version 1" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("deletes after confirmation and returns to the list", async () => {
    const deleted = [];
    renderApp({
      path: "/documents/d-1",
      routes: routes({
        "DELETE /documents/d-1": (request) => {
          deleted.push(request);
          return { status: 204 };
        },
      }),
    });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Delete document" }));
    await user.click(screen.getByRole("button", { name: "Yes, delete document" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Documents" })).toBeInTheDocument();
    expect(deleted).toHaveLength(1);
    expect(deleted[0].query.get("organization_id")).toBe("org-a");
  });

  it("shows a refused delete", async () => {
    renderApp({
      path: "/documents/d-1",
      routes: routes({ "DELETE /documents/d-1": forbidden("You need the member role.") }),
    });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Delete document" }));
    await user.click(screen.getByRole("button", { name: "Yes, delete document" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You need the member role.");
  });

  it("hides delete from viewers", async () => {
    renderApp({ path: "/documents/d-1", routes: routes({}, "viewer", USER) });

    await screen.findByRole("region", { name: "Details" });
    expect(screen.queryByRole("button", { name: "Delete document" })).not.toBeInTheDocument();
  });

  it("shows an unknown document", async () => {
    renderApp({ path: "/documents/d-9", routes: routes() });
    expect(await screen.findByRole("alert")).toHaveTextContent("Not found.");
  });

  it("does not keep the document after switching organization", async () => {
    renderApp({ path: "/documents/d-1", routes: routes() });
    const user = userEvent.setup();

    await screen.findByRole("region", { name: "Text" });
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    expect(await screen.findByText("Document was not found.")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByText("The harbour closed at noon.")).not.toBeInTheDocument(),
    );
    expect(screen.queryByRole("region", { name: "Revisions" })).not.toBeInTheDocument();
  });
});
