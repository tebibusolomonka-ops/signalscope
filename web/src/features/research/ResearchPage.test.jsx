import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { held, page, researchSession as session, source } from "../../test/content.js";
import { USER, signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

function routes(extra = {}, role = "member", user = USER) {
  return {
    ...signedIn(user),
    ...organizations([HARBOUR, RIVER], role),
    "GET /sources": page([source(), source({ id: "s-2", name: "Harbour Site" })]),
    "GET /research/sessions": page([
      session(),
      session({ id: "rs-2", title: null, retrieval_mode: "lexical", source_id: "s-2" }),
    ]),
    ...extra,
  };
}

describe("research sessions", () => {
  it("lists the organization's sessions", async () => {
    const { calls } = renderApp({ path: "/research", routes: routes() });

    const link = await screen.findByRole("link", { name: "Closure questions" });
    expect(link).toHaveAttribute("href", "/research/rs-1");
    expect(link.closest("tr")).toHaveTextContent("All sources");
    const second = screen.getByRole("link", { name: "Untitled session" }).closest("tr");
    expect(second).toHaveTextContent("lexical");
    expect(await within(second).findByRole("link", { name: "Harbour Site" })).toHaveAttribute(
      "href",
      "/sources/s-2",
    );
    const call = calls.find((item) => item.path === "/research/sessions");
    expect(call.query.get("organization_id")).toBe("org-a");
  });

  it("starts a session with a mode and source and opens it", async () => {
    let posted = null;
    renderApp({
      path: "/research",
      routes: routes({
        "POST /research/sessions": ({ body }) => {
          posted = body;
          return { status: 201, body: session({ id: "rs-9", ...body }) };
        },
      }),
    });
    const user = userEvent.setup();

    const form = await screen.findByRole("region", { name: "Start a research session" });
    await within(form).findByRole("option", { name: "Harbour Site" });
    await user.type(within(form).getByLabelText("Title (optional)"), "Fuel prices");
    await user.selectOptions(within(form).getByLabelText("Retrieval mode"), "reranked");
    await user.selectOptions(within(form).getByLabelText("Source"), "s-2");
    await user.click(within(form).getByRole("button", { name: "Start session" }));

    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Start a research session" })).toBeNull(),
    );
    expect(posted).toEqual({
      title: "Fuel prices",
      retrieval_mode: "reranked",
      source_id: "s-2",
      organization_id: "org-a",
    });
  });

  it("shows a refused start", async () => {
    renderApp({
      path: "/research",
      routes: routes({
        "POST /research/sessions": {
          status: 403,
          body: { error: { code: "forbidden", message: "You need the member role." } },
        },
      }),
    });
    const user = userEvent.setup();

    const form = await screen.findByRole("region", { name: "Start a research session" });
    await user.click(within(form).getByRole("button", { name: "Start session" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent("You need the member role.");
  });

  it("lets viewers read but not start sessions", async () => {
    renderApp({ path: "/research", routes: routes({}, "viewer") });

    await screen.findByText("Closure questions");
    expect(screen.queryByRole("region", { name: "Start a research session" })).toBeNull();
    expect(screen.getByText(/can read sessions but not start one/)).toBeInTheDocument();
  });

  it("drops the old organization's sessions when switching", async () => {
    const river = held();
    renderApp({
      path: "/research",
      routes: routes({
        "GET /research/sessions": async ({ query }) => {
          if (query.get("organization_id") === "org-b") {
            await river.ready;
            return page([
              session({ id: "rs-b", title: "River questions", organization_id: "org-b" }),
            ]);
          }
          return page([session()]);
        },
      }),
    });
    const user = userEvent.setup();

    await screen.findByText("Closure questions");
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    await waitFor(() => expect(screen.queryByText("Closure questions")).not.toBeInTheDocument());
    river.release();
    expect(await screen.findByText("River questions")).toBeInTheDocument();
  });
});
