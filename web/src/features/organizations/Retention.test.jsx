import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ADMIN, USER, signedIn } from "../../test/fakeApi.js";
import { renderApp } from "../../test/renderApp.jsx";

const ORG = {
  id: "org-1",
  name: "Harbour Watch",
  slug: "harbour-watch",
  created_by_user_id: "u-admin",
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};
const SUMMARY = {
  organization: ORG,
  members: { total: 1, owner: 1, admin: 0, member: 0, viewer: 0 },
  member_status: { active: 1, inactive: 0 },
  invitations: { pending: 0, accepted: 0, revoked: 0, expired: 0 },
  investigations: { open: 0, closed: 0 },
  collaborators: { owner: 1, editor: 0, viewer: 0 },
};

function policy(days) {
  return {
    organization_id: "org-1",
    security_audit_days: days,
    updated_at: days === null ? null : "2026-10-01T00:00:00Z",
  };
}

function preview(days, eligible, cutoff = null) {
  return { organization_id: "org-1", retention_days: days, cutoff, eligible_count: eligible };
}

function routes(overrides = {}, { user = ADMIN, role = "owner" } = {}) {
  return {
    ...signedIn(user),
    "GET /organizations": { body: [{ organization: ORG, role }] },
    "GET /organizations/org-1": { body: ORG },
    "GET /organizations/org-1/members": {
      body: [{ user: { id: user.id, email: user.email, display_name: user.display_name }, role }],
    },
    "GET /organizations/org-1/invitations": { body: [] },
    "GET /organizations/org-1/access-summary": { body: SUMMARY },
    "GET /organizations/org-1/retention": { body: policy(null) },
    "GET /organizations/org-1/retention/audit-preview": { body: preview(null, 0) },
    ...overrides,
  };
}

async function retentionSection() {
  return screen.findByRole("region", { name: "Audit retention" });
}

describe("audit retention workspace", () => {
  it("shows indefinite retention by default", async () => {
    renderApp({ path: "/organizations/org-1", routes: routes() });

    const section = await retentionSection();
    expect(await within(section).findByText("Retained indefinitely")).toBeInTheDocument();
    expect(
      within(section).getByText("Events eligible for deletion").nextElementSibling,
    ).toHaveTextContent("0");
  });

  it("shows a configured policy and its eligible count", async () => {
    renderApp({
      path: "/organizations/org-1",
      routes: routes({
        "GET /organizations/org-1/retention": { body: policy(90) },
        "GET /organizations/org-1/retention/audit-preview": {
          body: preview(90, 7, "2026-07-01T00:00:00Z"),
        },
      }),
    });

    const section = await retentionSection();
    expect(await within(section).findByText("90 days")).toBeInTheDocument();
    expect(
      within(section).getByText("Events eligible for deletion").nextElementSibling,
    ).toHaveTextContent("7");
    expect(within(section).getByText("2026-07-01 00:00 UTC")).toBeInTheDocument();
  });

  it("lets a system admin set a policy", async () => {
    let sent = null;
    renderApp({
      path: "/organizations/org-1",
      routes: routes({
        "PUT /organizations/org-1/retention": ({ body }) => {
          sent = body;
          return { body: policy(body.security_audit_days) };
        },
        "GET /organizations/org-1/retention": () => ({
          body: policy(sent ? sent.security_audit_days : null),
        }),
        "GET /organizations/org-1/retention/audit-preview": () => ({
          body: preview(sent ? sent.security_audit_days : null, 0),
        }),
      }),
    });
    const user = userEvent.setup();

    const section = await retentionSection();
    const form = await within(section).findByRole("form", { name: "Set retention" });
    await user.selectOptions(within(form).getByLabelText("Keep audit events"), "days");
    const days = within(form).getByLabelText("Days");
    await user.clear(days);
    await user.type(days, "120");
    await user.click(within(form).getByRole("button", { name: "Save policy" }));

    await waitFor(() => expect(sent).toEqual({ security_audit_days: 120 }));
    expect(await within(section).findByText("120 days")).toBeInTheDocument();
  });

  it("deletes eligible events after confirmation", async () => {
    let deleted = false;
    renderApp({
      path: "/organizations/org-1",
      routes: routes({
        "GET /organizations/org-1/retention": () => ({ body: policy(30) }),
        "GET /organizations/org-1/retention/audit-preview": () => ({
          body: preview(30, deleted ? 0 : 5, "2026-09-01T00:00:00Z"),
        }),
        "POST /organizations/org-1/retention/audit-cleanup": () => {
          deleted = true;
          return {
            body: {
              organization_id: "org-1",
              retention_days: 30,
              cutoff: "2026-09-01T00:00:00Z",
              deleted_count: 5,
            },
          };
        },
      }),
    });
    const user = userEvent.setup();

    const section = await retentionSection();
    await user.click(await within(section).findByRole("button", { name: "Delete eligible events" }));
    await user.click(within(section).getByRole("button", { name: "Yes, delete events" }));

    await waitFor(() =>
      expect(
        within(section).getByText("Events eligible for deletion").nextElementSibling,
      ).toHaveTextContent("0"),
    );
    expect(deleted).toBe(true);
  });

  it("lets an owner view and preview but not change", async () => {
    renderApp({
      path: "/organizations/org-1",
      routes: routes(
        {
          "GET /organizations/org-1/retention": { body: policy(90) },
          "GET /organizations/org-1/retention/audit-preview": { body: preview(90, 2) },
        },
        { user: USER, role: "owner" },
      ),
    });

    const section = await retentionSection();
    expect(await within(section).findByText("90 days")).toBeInTheDocument();
    expect(
      within(section).getByText("Only system admins can change retention or delete events."),
    ).toBeInTheDocument();
    expect(within(section).queryByRole("form", { name: "Set retention" })).not.toBeInTheDocument();
    expect(
      within(section).queryByRole("button", { name: "Delete eligible events" }),
    ).not.toBeInTheDocument();
  });

  it("shows a refused change", async () => {
    renderApp({
      path: "/organizations/org-1",
      routes: routes({
        "GET /organizations/org-1/retention": { body: policy(90) },
        "GET /organizations/org-1/retention/audit-preview": { body: preview(90, 2) },
        "PUT /organizations/org-1/retention": {
          status: 403,
          body: {
            error: { code: "forbidden", message: "Only system admins can change audit retention." },
          },
        },
      }),
    });
    const user = userEvent.setup();

    const section = await retentionSection();
    await user.click(await within(section).findByRole("button", { name: "Save policy" }));
    expect(await within(section).findByRole("alert")).toHaveTextContent(
      "Only system admins can change audit retention.",
    );
  });
});
