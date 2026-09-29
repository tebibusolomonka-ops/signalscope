import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { held, page, source } from "../../test/content.js";
import { USER, signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

function routes(extra = {}, role = "owner", user) {
  return {
    ...signedIn(user),
    ...organizations([HARBOUR, RIVER], role),
    "GET /sources": page([source(), source({ id: "s-2", name: "Harbour Site", type: "web" })]),
    ...extra,
  };
}

describe("sources workspace", () => {
  it("lists the sources of the active organization", async () => {
    const { calls } = renderApp({
      path: "/sources",
      routes: routes({
        "GET /sources": page([
          source({ ingestion_enabled: true, ingestion_interval_minutes: 30 }),
          source({ id: "s-2", name: "Harbour Uploads", type: "upload", url: null }),
        ]),
      }),
    });

    const row = (await screen.findByText("Harbour Feed")).closest("tr");
    expect(within(row).getByText("https://harbour.example/feed.xml")).toBeInTheDocument();
    expect(within(row).getByText("Every 30 min")).toBeInTheDocument();
    expect(screen.getByText("Harbour Uploads").closest("tr")).toHaveTextContent("Not scheduled");
    expect(screen.getByText("Showing 1 to 2 of 2")).toBeInTheDocument();
    const call = calls.find((item) => item.path === "/sources");
    expect(call.query.get("organization_id")).toBe("org-a");
    expect(call.query.get("limit")).toBe("50");
  });

  it("says when there are no sources", async () => {
    renderApp({ path: "/sources", routes: routes({ "GET /sources": page([]) }) });
    expect(await screen.findByText("This organization has no sources yet.")).toBeInTheDocument();
  });

  it("adds a source to the active organization", async () => {
    let created = null;
    renderApp({
      path: "/sources",
      routes: routes({
        "POST /sources": ({ body, query }) => {
          created = { body, query };
          return { status: 201, body: source({ id: "s-9", name: body.name, url: body.url }) };
        },
      }),
    });
    const user = userEvent.setup();

    const form = await screen.findByRole("region", { name: "Add a source" });
    await user.selectOptions(within(form).getByLabelText("Type"), "web");
    await user.type(within(form).getByLabelText("Name"), "Harbour News");
    await user.type(within(form).getByLabelText("URL"), "https://news.example");
    await user.click(within(form).getByRole("button", { name: "Add source" }));

    expect(await screen.findByText('Source "Harbour News" was added.')).toBeInTheDocument();
    expect(created.body).toEqual({
      type: "web",
      name: "Harbour News",
      url: "https://news.example",
      organization_id: "org-a",
    });
    expect(created.query.get("organization_id")).toBe("org-a");
  });

  it("shows the API refusal and hides the form for viewers", async () => {
    renderApp({
      path: "/sources",
      routes: routes(
        {
          "GET /sources": {
            status: 403,
            body: { error: { code: "forbidden", message: "You cannot read this content." } },
          },
        },
        "viewer",
        USER,
      ),
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("You cannot read this content.");
    expect(screen.queryByRole("region", { name: "Add a source" })).not.toBeInTheDocument();
  });

  it("hides the form for members, who cannot manage sources", async () => {
    renderApp({ path: "/sources", routes: routes({}, "member", USER) });
    await screen.findByText("Harbour Feed");
    expect(screen.queryByRole("region", { name: "Add a source" })).not.toBeInTheDocument();
  });

  it("drops the old organization's sources while the new ones load", async () => {
    const river = held();
    const { calls } = renderApp({
      path: "/sources",
      routes: routes({
        "GET /sources": async ({ query }) => {
          if (query.get("organization_id") === "org-b") {
            await river.ready;
            return page([source({ id: "s-b", name: "River Feed", organization_id: "org-b" })]);
          }
          return page([source()]);
        },
      }),
    });
    const user = userEvent.setup();

    await screen.findByText("Harbour Feed");
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    await waitFor(() => expect(screen.queryByText("Harbour Feed")).not.toBeInTheDocument());
    river.release();
    expect(await screen.findByText("River Feed")).toBeInTheDocument();
    expect(screen.queryByText("Harbour Feed")).not.toBeInTheDocument();
    const last = calls.filter((item) => item.path === "/sources").at(-1);
    expect(last.query.get("organization_id")).toBe("org-b");
  });
});
