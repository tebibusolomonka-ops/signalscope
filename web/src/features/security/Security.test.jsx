import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ADMIN, TOKEN, signedIn } from "../../test/fakeApi.js";
import { renderApp } from "../../test/renderApp.jsx";

const HARBOUR = { id: "org-1", name: "Harbour Watch", slug: "harbour-watch" };
const RIVER = { id: "org-2", name: "River Desk", slug: "river-desk" };
const EVENT = {
  id: "e-1",
  actor: { id: "u-admin", email: "admin@example.org", display_name: "Admin" },
  organization_id: "org-1",
  action: "organization.member_added",
  resource_type: "organization",
  resource_id: "org-1",
  metadata: { user_id: "u-ana", role: "member" },
  created_at: "2026-10-01T12:00:00Z",
};
const SESSIONS = [
  {
    session_id: "s-1",
    created_at: "2026-10-01T10:00:00Z",
    expires_at: "2026-10-08T10:00:00Z",
    last_seen_at: "2026-10-01T11:00:00Z",
    revoked: false,
    revoked_at: null,
    current_session: true,
  },
  {
    session_id: "s-2",
    created_at: "2026-09-30T10:00:00Z",
    expires_at: "2026-10-07T10:00:00Z",
    last_seen_at: "2026-09-30T11:00:00Z",
    revoked: false,
    revoked_at: null,
    current_session: false,
  },
];

function routes(user, organizations, extra = {}) {
  return {
    ...signedIn(user),
    "GET /organizations": { body: organizations },
    "GET /security/audit": ({ query }) => ({
      body: { items: [EVENT], total: 1, limit: Number(query.get("limit")), offset: 0 },
    }),
    "GET /auth/sessions": { body: SESSIONS },
    ...extra,
  };
}

describe("security page", () => {
  it("lets a system admin read every event and filter by date", async () => {
    const { calls } = renderApp({ path: "/security", routes: routes(ADMIN, []) });
    const user = userEvent.setup();

    expect(await screen.findByRole("cell", { name: "organization.member_added" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "user_id: u-ana, role: member" })).toBeInTheDocument();
    expect(screen.getByLabelText("Organization")).toHaveValue("");

    await user.type(screen.getByLabelText("Action"), "auth.login");
    await user.type(screen.getByLabelText("From (UTC)"), "2026-10-01");
    await user.type(screen.getByLabelText("To (UTC)"), "2026-10-02");
    await user.click(screen.getByRole("button", { name: "Search audit log" }));

    await waitFor(() => {
      const query = calls.filter((call) => call.path === "/security/audit").at(-1).query;
      expect(query.get("action")).toBe("auth.login");
      expect(query.get("created_from")).toBe("2026-10-01T00:00:00Z");
      expect(query.get("created_to")).toBe("2026-10-03T00:00:00.000Z");
      expect(query.has("organization_id")).toBe(false);
    });
  });

  it("limits organization admins to the organizations they manage", async () => {
    const member = { ...ADMIN, is_system_admin: false };
    const { calls } = renderApp({
      path: "/security",
      routes: routes(member, [
        { organization: HARBOUR, role: "admin" },
        { organization: RIVER, role: "viewer" },
      ]),
    });

    const select = await screen.findByLabelText("Organization");
    expect(within(select).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Harbour Watch",
    ]);
    await screen.findByRole("cell", { name: "organization.member_added" });
    const audit = calls.find((call) => call.path === "/security/audit");
    expect(audit.query.get("organization_id")).toBe("org-1");
  });

  it("explains that members have no audit access", async () => {
    const member = { ...ADMIN, is_system_admin: false };
    const { calls } = renderApp({
      path: "/security",
      routes: routes(member, [{ organization: HARBOUR, role: "member" }]),
    });

    expect(await screen.findByText(/The audit log is for system admins/)).toBeInTheDocument();
    expect(calls.some((call) => call.path === "/security/audit")).toBe(false);
  });

  it("revokes another session and signs out everywhere", async () => {
    const { calls } = renderApp({
      path: "/security",
      routes: routes(ADMIN, [], {
        "DELETE /auth/sessions/s-2": { status: 204 },
        "POST /auth/logout-all": { status: 204 },
      }),
    });
    const user = userEvent.setup();

    expect(await screen.findByText("This session")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /2026-10-01T10:00:00Z/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Revoke session started 2026-09-30T10:00:00Z" }));
    await waitFor(() => expect(calls.some((call) => call.method === "DELETE")).toBe(true));
    expect(document.body.innerHTML).not.toContain(TOKEN);

    await user.click(screen.getByRole("button", { name: "Sign out everywhere" }));

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(sessionStorage.getItem("signalscope.session")).toBeNull();
  });

  it("signs out other sessions while keeping the current one", async () => {
    const { calls } = renderApp({
      path: "/security",
      routes: routes(ADMIN, [], {
        "POST /auth/sessions/revoke-others": { body: { revoked_sessions: 1 } },
      }),
    });
    const user = userEvent.setup();

    await screen.findByText("This session");
    await user.click(screen.getByRole("button", { name: "Sign out other sessions" }));

    await waitFor(() =>
      expect(calls.some((call) => call.path === "/auth/sessions/revoke-others")).toBe(true),
    );
    // The current session remains, so the page did not sign out.
    expect(screen.queryByRole("heading", { name: "Sign in" })).not.toBeInTheDocument();
  });
});

describe("admin session controls", () => {
  it("lists and revokes another user's sessions", async () => {
    const ana = {
      id: "u-ana",
      email: "ana@example.org",
      display_name: "Ana",
      is_active: true,
      is_system_admin: false,
      created_at: "x",
      updated_at: "x",
    };
    const sessions = [
      {
        session_id: "s-9",
        created_at: "2026-10-01T09:00:00Z",
        expires_at: "2026-10-08T09:00:00Z",
        last_seen_at: "2026-10-01T09:00:00Z",
        revoked_at: null,
        active: true,
      },
    ];
    const { calls } = renderApp({
      path: "/users",
      routes: {
        ...signedIn(),
        "GET /admin/users": { body: { items: [ana], total: 1, limit: 20, offset: 0 } },
        "GET /admin/users/u-ana/sessions": () => ({ body: sessions }),
        "DELETE /admin/users/u-ana/sessions/s-9": () => {
          sessions[0] = { ...sessions[0], active: false, revoked_at: "2026-10-01T10:00:00Z" };
          return { status: 204 };
        },
        "POST /admin/users/u-ana/revoke-sessions": { body: { revoked_sessions: 0 } },
      },
    });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Sessions of Ana" }));
    const section = await screen.findByRole("region", { name: "Sessions of Ana" });
    await user.click(
      await within(section).findByRole("button", { name: "Revoke session started 2026-10-01T09:00:00Z" }),
    );
    await waitFor(() => expect(within(section).getByRole("cell", { name: "No" })).toBeInTheDocument());
    await user.click(within(section).getByRole("button", { name: "Revoke all sessions of Ana" }));

    expect(await within(section).findByRole("status")).toHaveTextContent("Revoked 0 sessions.");
    expect(calls.map((call) => `${call.method} ${call.path}`)).toContain(
      "POST /admin/users/u-ana/revoke-sessions",
    );
  });
});
