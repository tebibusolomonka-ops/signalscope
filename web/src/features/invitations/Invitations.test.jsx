import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { signedIn } from "../../test/fakeApi.js";
import { renderApp } from "../../test/renderApp.jsx";

const INVITE_TOKEN = "one-time-invitation-token";
const ORG = { id: "org-1", name: "Harbour Watch", slug: "harbour-watch" };

function invitation(id, email, status = "pending") {
  return {
    id,
    organization_id: "org-1",
    email,
    role: "member",
    status,
    expires_at: "2026-10-08T00:00:00Z",
    accepted_at: null,
    revoked_at: null,
    invited_by_user_id: "u-admin",
    created_at: "2026-10-01T00:00:00Z",
  };
}

function routes(invitations) {
  return {
    ...signedIn(),
    "GET /organizations": { body: [{ organization: ORG, role: "owner" }] },
    "GET /organizations/org-1": { body: ORG },
    "GET /organizations/org-1/members": { body: [] },
    "GET /organizations/org-1/access-summary": {
      status: 403,
      body: { error: { code: "forbidden", message: "No summary." } },
    },
    "GET /organizations/org-1/invitations": () => ({ body: invitations }),
    "POST /organizations/org-1/invitations": ({ body }) => {
      const created = { ...invitation("i-new", body.email), role: body.role };
      invitations.unshift(created);
      return { status: 201, body: { invitation: created, invitation_token: INVITE_TOKEN } };
    },
    "DELETE /organizations/org-1/invitations/i-1": () => {
      invitations.find((item) => item.id === "i-1").status = "revoked";
      return { status: 204 };
    },
  };
}

describe("invitations", () => {
  it("lists invitations and revokes a pending one", async () => {
    const invitations = [invitation("i-1", "ana@example.org"), invitation("i-2", "ben@example.org", "accepted")];
    renderApp({ path: "/organizations/org-1", routes: routes(invitations) });
    const user = userEvent.setup();

    const section = await screen.findByRole("region", { name: "Invitations" });
    expect(await within(section).findByText("ana@example.org")).toBeInTheDocument();
    expect(within(section).queryByRole("button", { name: /ben@example.org/ })).not.toBeInTheDocument();

    await user.click(within(section).getByRole("button", { name: "Revoke invitation for ana@example.org" }));

    expect(await within(section).findByText("revoked")).toBeInTheDocument();
  });

  it("shows a new token once and never stores it", async () => {
    const invitations = [];
    renderApp({ path: "/organizations/org-1", routes: routes(invitations) });
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Invite email"), "cleo@example.org");
    await user.selectOptions(screen.getByLabelText("Invite as"), "viewer");
    await user.click(screen.getByRole("button", { name: "Create invitation" }));

    const token = await screen.findByLabelText("Invitation token");
    expect(token).toHaveValue(INVITE_TOKEN);
    expect(Object.values({ ...sessionStorage })).not.toContain(INVITE_TOKEN);
    expect(localStorage.length).toBe(0);
    const section = screen.getByRole("region", { name: "Invitations" });
    expect(await within(section).findByRole("cell", { name: "cleo@example.org" })).toBeInTheDocument();
    expect(within(section).getByRole("cell", { name: "viewer" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Done" }));

    await waitFor(() => expect(document.body.innerHTML).not.toContain(INVITE_TOKEN));
  });

  it("shows the API's errors", async () => {
    const all = routes([]);
    all["POST /organizations/org-1/invitations"] = {
      status: 409,
      body: { error: { code: "conflict", message: "An invitation for this email is already pending." } },
    };
    renderApp({ path: "/organizations/org-1", routes: all });
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Invite email"), "ana@example.org");
    await user.click(screen.getByRole("button", { name: "Create invitation" }));

    const alerts = await screen.findAllByRole("alert");
    expect(alerts.map((alert) => alert.textContent)).toContain(
      "An invitation for this email is already pending.",
    );
  });
});

describe("accept invitation", () => {
  it("accepts a pasted token", async () => {
    const { calls } = renderApp({
      path: "/accept-invitation",
      routes: {
        ...signedIn(),
        "POST /organization-invitations/accept": { body: { organization: ORG, role: "member" } },
      },
    });
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Invitation token"), `  ${INVITE_TOKEN} `);
    await user.click(screen.getByRole("button", { name: "Accept invitation" }));

    expect(await screen.findByRole("status")).toHaveTextContent("You joined Harbour Watch as member.");
    expect(calls.at(-1).body).toEqual({ token: INVITE_TOKEN });
    expect(screen.getByLabelText("Invitation token")).toHaveValue("");
  });

  it("shows why a token was refused", async () => {
    renderApp({
      path: "/accept-invitation",
      routes: {
        ...signedIn(),
        "POST /organization-invitations/accept": {
          status: 404,
          body: {
            error: { code: "not_found", message: "Invitation was not found or can no longer be used." },
          },
        },
      },
    });
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Invitation token"), "used-token");
    await user.click(screen.getByRole("button", { name: "Accept invitation" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Invitation was not found or can no longer be used.",
    );
  });
});
