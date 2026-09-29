import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DASHBOARD_ROUTES } from "../test/dashboardRoutes.js";
import { ADMIN, TOKEN } from "../test/fakeApi.js";
import { renderApp } from "../test/renderApp.jsx";

const PASSWORD = "a long test password";
const ORG = { id: "org-1", name: "Harbour Watch", slug: "harbour-watch" };

const ROUTES = {
  "POST /auth/login": {
    body: { access_token: TOKEN, token_type: "bearer", expires_at: "x", user: ADMIN },
  },
  "POST /auth/logout": { status: 204 },
  ...DASHBOARD_ROUTES,
  "GET /organizations": { body: [{ organization: ORG, role: "owner" }] },
  "GET /organizations/org-1": { body: ORG },
  "GET /organizations/org-1/members": {
    body: [
      { user: { id: "u-admin", email: "admin@example.org", display_name: "Admin" }, role: "owner" },
    ],
  },
  "GET /organizations/org-1/access-summary": {
    body: {
      organization: ORG,
      members: { total: 1, owner: 1, admin: 0, member: 0, viewer: 0 },
      member_status: { active: 1, inactive: 0 },
      invitations: { pending: 1, accepted: 0, revoked: 0, expired: 0 },
      investigations: { open: 0, closed: 0 },
      collaborators: { owner: 0, editor: 0, viewer: 0 },
    },
  },
  "GET /organizations/org-1/invitations": {
    body: [
      {
        id: "i-1",
        organization_id: "org-1",
        email: "cleo@example.org",
        role: "member",
        status: "pending",
        expires_at: "2026-10-08T00:00:00Z",
        accepted_at: null,
        revoked_at: null,
        invited_by_user_id: "u-admin",
        created_at: "2026-10-01T00:00:00Z",
      },
    ],
  },
  "GET /security/audit": {
    body: {
      items: [
        {
          id: "e-1",
          actor: { id: "u-admin", email: "admin@example.org", display_name: "Admin" },
          organization_id: null,
          action: "auth.login",
          resource_type: "user_session",
          resource_id: "s-1",
          metadata: {},
          created_at: "2026-10-01T12:00:00Z",
        },
      ],
      total: 1,
      limit: 20,
      offset: 0,
    },
  },
  "GET /auth/sessions": { body: [] },
};

describe("admin flow", () => {
  it("signs in, visits every workspace and signs out", async () => {
    const { calls } = renderApp({ path: "/login", routes: ROUTES });
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Email"), "admin@example.org");
    await user.type(screen.getByLabelText("Password"), PASSWORD);
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("region", { name: "Records and open jobs" })).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Organizations" }));
    await user.click(await screen.findByRole("link", { name: "Harbour Watch" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Harbour Watch" })).toBeInTheDocument();
    const invitations = screen.getByRole("region", { name: "Invitations" });
    expect(await within(invitations).findByText("cleo@example.org")).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Security" }));
    expect(await screen.findByRole("cell", { name: "auth.login" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Sign out" }));

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    await waitFor(() => expect(sessionStorage.getItem("signalscope.session")).toBeNull());
    expect(calls.at(-1).path).toBe("/auth/logout");
    expect(localStorage.length).toBe(0);
    for (const call of calls) {
      expect(call.path).not.toContain(TOKEN);
    }
  });
});
