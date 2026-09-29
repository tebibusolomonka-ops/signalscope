import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { forbidden, notFound, page, provenance, source } from "../../test/content.js";
import { USER, signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

function routes(extra = {}, role = "owner", user) {
  return {
    ...signedIn(user),
    ...organizations([HARBOUR, RIVER], role),
    "GET /sources": page([source()]),
    "GET /sources/s-1": ({ query }) =>
      query.get("organization_id") === "org-a"
        ? { body: source() }
        : notFound("Source was not found."),
    "GET /sources/s-1/provenance": { body: provenance() },
    ...extra,
  };
}

describe("source detail", () => {
  it("shows the configuration and observed provenance", async () => {
    renderApp({
      path: "/sources/s-1",
      routes: routes({
        "GET /sources/s-1": {
          body: source({
            ingestion_enabled: true,
            ingestion_interval_minutes: 60,
            next_ingestion_at: "2026-10-01T09:30:00Z",
          }),
        },
      }),
    });

    expect(
      await screen.findByRole("heading", { level: 1, name: "Harbour Feed" }),
    ).toBeInTheDocument();
    const config = screen.getByRole("region", { name: "Configuration" });
    expect(within(config).getByText("Every 60 min")).toBeInTheDocument();
    expect(within(config).getByText("2026-10-01 09:30 UTC")).toBeInTheDocument();

    const facts = await screen.findByRole("region", { name: "Provenance" });
    await within(facts).findByText("Documents");
    expect(within(facts).getByText("Documents").nextElementSibling).toHaveTextContent("12");
    expect(
      within(facts).getByText("Event clusters also reported by other sources").nextElementSibling,
    ).toHaveTextContent("2");
    expect(within(facts).getByText("First published").nextElementSibling).toHaveTextContent("-");
    expect(facts).not.toHaveTextContent(/credib|reliab|trust|score:/i);
  });

  it("deletes only after confirmation", async () => {
    const deletes = [];
    renderApp({
      path: "/sources/s-1",
      routes: routes({
        "DELETE /sources/s-1": (request) => {
          deletes.push(request);
          return { status: 204 };
        },
      }),
    });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Delete source" }));
    const question = screen.getByRole("group", { name: "Delete source" });
    expect(within(question).getByRole("button", { name: "Yes, delete source" })).toHaveFocus();
    await user.click(within(question).getByRole("button", { name: "Cancel" }));
    expect(deletes).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Delete source" })).toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Delete source" }));
    await user.click(screen.getByRole("button", { name: "Yes, delete source" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Sources" })).toBeInTheDocument();
    expect(deletes).toHaveLength(1);
    expect(deletes[0].query.get("organization_id")).toBe("org-a");
  });

  it("shows a refused delete", async () => {
    renderApp({
      path: "/sources/s-1",
      routes: routes({ "DELETE /sources/s-1": forbidden("You need the owner or admin role.") }),
    });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Delete source" }));
    await user.click(screen.getByRole("button", { name: "Yes, delete source" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("You need the owner or admin role.");
    expect(screen.getByRole("heading", { level: 1, name: "Harbour Feed" })).toBeInTheDocument();
  });

  it("hides delete from viewers", async () => {
    renderApp({ path: "/sources/s-1", routes: routes({}, "viewer", USER) });

    await screen.findByRole("region", { name: "Configuration" });
    expect(screen.queryByRole("button", { name: "Delete source" })).not.toBeInTheDocument();
  });

  it("shows an unknown source", async () => {
    renderApp({
      path: "/sources/s-9",
      routes: routes({ "GET /sources/s-9": notFound("Source was not found.") }),
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("Source was not found.");
  });

  it("does not keep the source after switching to an organization that cannot see it", async () => {
    renderApp({ path: "/sources/s-1", routes: routes() });
    const user = userEvent.setup();

    await screen.findByRole("heading", { level: 1, name: "Harbour Feed" });
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    expect(await screen.findByText("Source was not found.")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Harbour Feed")).not.toBeInTheDocument());
    expect(screen.queryByRole("region", { name: "Provenance" })).not.toBeInTheDocument();
  });

  it("is reached from the source list", async () => {
    renderApp({ path: "/sources", routes: routes() });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("link", { name: "Harbour Feed" }));
    expect(await screen.findByRole("region", { name: "Configuration" })).toBeInTheDocument();
  });
});
