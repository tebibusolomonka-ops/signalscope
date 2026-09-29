import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { investigation } from "../../test/content.js";
import { ADMIN, USER, signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

function person(id, name) {
  return { id, email: `${name.toLowerCase()}@example.org`, display_name: name };
}

const OWNER = person("u-owner", "Olga");
const ED = person("u-ed", "Ed");
const VIV = person("u-viv", "Viv");

function collaborator(user, role) {
  return { user, role, created_at: "2026-09-10T08:00:00Z", updated_at: "2026-09-10T08:00:00Z" };
}

function routes(state, { role = "owner", user = ADMIN, status = "open" } = {}) {
  return {
    ...signedIn(user),
    ...organizations([HARBOUR, RIVER], role),
    "GET /investigations/inv-1": { body: investigation({ status }) },
    "GET /investigations/inv-1/items": { body: [] },
    "GET /investigations/inv-1/members": () => ({ body: state.members }),
    "GET /organizations/org-a/members": {
      body: [OWNER, ED, VIV].map((member) => ({
        user: member,
        role: "member",
        created_at: "2026-09-01T00:00:00Z",
        updated_at: "2026-09-01T00:00:00Z",
      })),
    },
    "POST /investigations/inv-1/members": ({ body }) => {
      state.calls.push(["add", body]);
      const added = [OWNER, ED, VIV].find((member) => member.id === body.user_id);
      state.members = [...state.members, collaborator(added, body.role)];
      return { status: 201, body: state.members.at(-1) };
    },
    "PATCH /investigations/inv-1/members/u-ed": ({ body }) => {
      state.calls.push(["change", body]);
      state.members = state.members.map((item) =>
        item.user.id === "u-ed" ? { ...item, role: body.role } : item,
      );
      return { body: state.members.find((item) => item.user.id === "u-ed") };
    },
    "DELETE /investigations/inv-1/members/u-ed": () => {
      state.calls.push(["remove"]);
      state.members = state.members.filter((item) => item.user.id !== "u-ed");
      return { status: 204 };
    },
    "PATCH /investigations/inv-1/members/u-owner": {
      status: 409,
      body: { error: { code: "conflict", message: "The last owner cannot be demoted." } },
    },
  };
}

function start() {
  return { members: [collaborator(OWNER, "owner"), collaborator(ED, "editor")], calls: [] };
}

async function section() {
  const found = await screen.findByRole("region", { name: "Collaborators" });
  await within(found).findByText("Olga (olga@example.org)");
  return found;
}

describe("investigation collaborators", () => {
  it("lists collaborators and their roles", async () => {
    renderApp({ path: "/investigations/inv-1", routes: routes(start()) });

    const found = await section();
    expect(within(found).getByLabelText("Role of Olga")).toHaveValue("owner");
    expect(within(found).getByLabelText("Role of Ed")).toHaveValue("editor");
  });

  it("adds an organization member who is not a collaborator yet", async () => {
    const state = start();
    renderApp({ path: "/investigations/inv-1", routes: routes(state) });
    const user = userEvent.setup();

    const found = await section();
    const form = within(found).getByRole("form", { name: "Add a collaborator" });
    const options = await within(form).findAllByRole("option", { name: /example\.org/ });
    expect(options.map((option) => option.textContent)).toEqual(["Viv (viv@example.org)"]);
    await user.selectOptions(within(form).getByLabelText("Role"), "editor");
    await user.click(within(form).getByRole("button", { name: "Add collaborator" }));

    expect(await within(found).findByLabelText("Role of Viv")).toHaveValue("editor");
    expect(state.calls).toEqual([["add", { user_id: "u-viv", role: "editor" }]]);
  });

  it("changes a role and removes a collaborator", async () => {
    const state = start();
    renderApp({ path: "/investigations/inv-1", routes: routes(state) });
    const user = userEvent.setup();

    const found = await section();
    await user.selectOptions(within(found).getByLabelText("Role of Ed"), "viewer");
    await waitFor(() => expect(within(found).getByLabelText("Role of Ed")).toHaveValue("viewer"));
    await user.click(within(found).getByRole("button", { name: "Remove Ed" }));

    await waitFor(() =>
      expect(
        within(found).queryByText("Ed (ed@example.org)", { selector: "td" }),
      ).not.toBeInTheDocument(),
    );
    expect(state.calls).toEqual([["change", { role: "viewer" }], ["remove"]]);
  });

  it("shows the API's last owner rule", async () => {
    renderApp({ path: "/investigations/inv-1", routes: routes(start()) });
    const user = userEvent.setup();

    const found = await section();
    await user.selectOptions(within(found).getByLabelText("Role of Olga"), "editor");

    expect(await within(found).findByRole("alert")).toHaveTextContent(
      "The last owner cannot be demoted.",
    );
    expect(within(found).getByLabelText("Role of Olga")).toHaveValue("owner");
  });

  it("shows roles without controls to an editor who is an organization viewer", async () => {
    const state = start();
    state.members = [collaborator(OWNER, "owner"), collaborator({ ...ED, id: USER.id }, "editor")];
    renderApp({
      path: "/investigations/inv-1",
      routes: routes(state, { role: "viewer", user: USER }),
    });

    const found = await section();
    expect(within(found).queryByRole("combobox")).not.toBeInTheDocument();
    expect(within(found).queryByRole("button", { name: /Remove/ })).not.toBeInTheDocument();
    expect(
      within(found).queryByRole("form", { name: "Add a collaborator" }),
    ).not.toBeInTheDocument();
    expect(found).toHaveTextContent("editor");
  });

  it("lets an investigation owner manage collaborators without an organization admin role", async () => {
    const state = start();
    state.members = [collaborator({ ...OWNER, id: USER.id }, "owner"), collaborator(ED, "editor")];
    renderApp({
      path: "/investigations/inv-1",
      routes: routes(state, { role: "member", user: USER }),
    });

    const found = await screen.findByRole("region", { name: "Collaborators" });
    expect(await within(found).findByLabelText("Role of Ed")).toBeInTheDocument();
  });

  it("keeps collaboration open on a closed investigation", async () => {
    renderApp({ path: "/investigations/inv-1", routes: routes(start(), { status: "closed" }) });

    const found = await section();
    expect(screen.getByText(/This investigation is closed and read only/)).toBeInTheDocument();
    expect(within(found).getByRole("form", { name: "Add a collaborator" })).toBeInTheDocument();
  });

  it("leaves nothing of the old organization after switching", async () => {
    renderApp({ path: "/investigations/inv-1", routes: routes(start()) });
    const user = userEvent.setup();

    await section();
    await user.selectOptions(screen.getByLabelText("Active organization"), "org-b");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "does not belong to the active organization",
    );
    expect(screen.queryByRole("region", { name: "Collaborators" })).not.toBeInTheDocument();
    expect(screen.queryByText("Olga (olga@example.org)")).not.toBeInTheDocument();
  });
});
