import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { signedIn } from "../../test/fakeApi.js";
import { renderApp } from "../../test/renderApp.jsx";

const ORG = {
  id: "org-1",
  name: "Harbour Watch",
  slug: "harbour-watch",
  created_by_user_id: "u-admin",
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};
const MEMBERS = [
  { user: { id: "u-admin", email: "admin@example.org", display_name: "Admin" }, role: "owner" },
  { user: { id: "u-ana", email: "ana@example.org", display_name: "Ana" }, role: "member" },
];
const SUMMARY = {
  organization: ORG,
  members: { total: 2, owner: 1, admin: 0, member: 1, viewer: 0 },
  member_status: { active: 2, inactive: 0 },
  invitations: { pending: 1, accepted: 0, revoked: 0, expired: 0 },
  investigations: { open: 3, closed: 1 },
  collaborators: { owner: 3, editor: 0, viewer: 0 },
};
const FORBIDDEN = {
  status: 403,
  body: { error: { code: "forbidden", message: "You do not have permission to manage these members." } },
};

function detailRoutes(overrides = {}) {
  return {
    ...signedIn(),
    "GET /organizations": { body: [{ organization: ORG, role: "owner" }] },
    "GET /organizations/org-1": { body: ORG },
    "GET /organizations/org-1/members": { body: MEMBERS },
    "GET /organizations/org-1/access-summary": { body: SUMMARY },
    ...overrides,
  };
}

describe("organizations list", () => {
  it("lists my organizations and creates one", async () => {
    const organizations = [{ organization: ORG, role: "owner" }];
    const created = { ...ORG, id: "org-2", name: "River Desk", slug: "river-desk" };
    const { calls } = renderApp({
      path: "/organizations",
      routes: {
        ...signedIn(),
        "GET /organizations": () => ({ body: organizations }),
        "POST /organizations": ({ body }) => {
          organizations.push({ organization: { ...created, ...body }, role: "owner" });
          return { status: 201, body: created };
        },
      },
    });

    expect(await screen.findByRole("link", { name: "Harbour Watch" })).toHaveAttribute(
      "href",
      "/organizations/org-1",
    );
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Name"), "River Desk");
    await user.type(screen.getByLabelText("Slug"), "river-desk");
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByRole("link", { name: "River Desk" })).toBeInTheDocument();
    expect(calls.find((call) => call.method === "POST").body).toEqual({
      name: "River Desk",
      slug: "river-desk",
    });
  });

  it("shows loading, then errors from the API", async () => {
    renderApp({
      path: "/organizations",
      routes: {
        ...signedIn(),
        "GET /organizations": { status: 503, body: { error: { code: "x", message: "Database is not configured." } } },
      },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("Database is not configured.");
  });
});

describe("organization detail", () => {
  it("shows the organization, my role, members and the access summary", async () => {
    renderApp({ path: "/organizations/org-1", routes: detailRoutes() });

    expect(await screen.findByRole("heading", { level: 1, name: "Harbour Watch" })).toBeInTheDocument();
    expect(screen.getByText("harbour-watch")).toBeInTheDocument();
    expect(screen.getByText("owner", { selector: "dd" })).toBeInTheDocument();
    expect(await screen.findByText("ana@example.org")).toBeInTheDocument();
    const summary = screen.getByRole("region", { name: "Access summary" });
    const investigations = await within(summary).findByRole("heading", { name: "Investigations" });
    expect(investigations.nextElementSibling).toHaveTextContent("open3");
  });

  it("changes a role, removes a member and adds one", async () => {
    const members = structuredClone(MEMBERS);
    const { calls } = renderApp({
      path: "/organizations/org-1",
      routes: detailRoutes({
        "GET /organizations/org-1/members": () => ({ body: members }),
        "PATCH /organizations/org-1/members/u-ana": ({ body }) => {
          members[1].role = body.role;
          return { body: members[1] };
        },
        "DELETE /organizations/org-1/members/u-ana": () => {
          members.splice(1, 1);
          return { status: 204 };
        },
        "POST /organizations/org-1/members": ({ body }) => ({ status: 201, body }),
      }),
    });
    const user = userEvent.setup();

    await user.selectOptions(await screen.findByLabelText("Role of Ana"), "viewer");
    await waitFor(() => expect(screen.getByLabelText("Role of Ana")).toHaveValue("viewer"));
    await user.click(screen.getByRole("button", { name: "Remove Ana" }));
    await waitFor(() => expect(screen.queryByText("ana@example.org")).not.toBeInTheDocument());
    await user.type(screen.getByLabelText("User ID"), " u-ben ");
    await user.selectOptions(screen.getByLabelText("New member role"), "admin");
    await user.click(screen.getByRole("button", { name: "Add member" }));

    await waitFor(() =>
      expect(calls.at(-2)).toMatchObject({
        method: "POST",
        body: { user_id: "u-ben", role: "admin" },
      }),
    );
    expect(calls.find((call) => call.method === "PATCH").body).toEqual({ role: "viewer" });
  });

  it("shows the API's 403 answers", async () => {
    renderApp({
      path: "/organizations/org-1",
      routes: detailRoutes({
        "PATCH /organizations/org-1/members/u-ana": FORBIDDEN,
        "GET /organizations/org-1/access-summary": {
          status: 403,
          body: {
            error: { code: "forbidden", message: "Only organization owners and admins can see this summary." },
          },
        },
      }),
    });
    const user = userEvent.setup();

    await user.selectOptions(await screen.findByLabelText("Role of Ana"), "admin");

    const alerts = await screen.findAllByRole("alert");
    const texts = alerts.map((alert) => alert.textContent);
    expect(texts).toContain("You do not have permission to manage these members.");
    expect(texts).toContain("Only organization owners and admins can see this summary.");
  });

  it("shows a missing organization", async () => {
    renderApp({
      path: "/organizations/org-9",
      routes: { ...signedIn(), "GET /organizations": { body: [] } },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("Not found.");
  });
});
