import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { USER, signedIn } from "../../test/fakeApi.js";
import { HARBOUR, RIVER, organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

function preview(overrides = {}) {
  return {
    organization_id: "org-a",
    security_audit_days: 90,
    cutoff: "2026-07-02T12:00:00Z",
    deletable_count: 4,
    total_count: 10,
    ...overrides,
  };
}

function routes(extra = {}, { role = "owner", user, previewBody = preview() } = {}) {
  return {
    ...signedIn(user),
    ...organizations([HARBOUR, RIVER], role),
    "GET /security/audit/retention/preview": { body: previewBody },
    ...extra,
  };
}

async function region() {
  return screen.findByRole("region", { name: "Security audit retention" });
}

describe("retention page", () => {
  it("shows the policy and how many events are past it", async () => {
    renderApp({ path: "/operations/retention", routes: routes() });

    const section = await region();
    expect(await within(section).findByText("90 days")).toBeInTheDocument();
    expect(within(section).getByText("4 of 10")).toBeInTheDocument();
    expect(within(section).getByText("2026-07-02 12:00 UTC")).toBeInTheDocument();
  });

  it("lets owners view but not edit", async () => {
    renderApp({ path: "/operations/retention", routes: routes({}, { role: "owner", user: USER }) });

    const section = await region();
    expect(
      await within(section).findByText("Only system admins can change the policy or run a cleanup."),
    ).toBeInTheDocument();
    expect(within(section).queryByRole("button", { name: "Save policy" })).not.toBeInTheDocument();
  });

  it("saves a new policy as a system admin", async () => {
    const sent = [];
    let body = preview();
    renderApp({
      path: "/operations/retention",
      routes: routes({
        "GET /security/audit/retention/preview": () => ({ body }),
        "PUT /security/audit/retention": (request) => {
          sent.push(request.body);
          body = preview({ security_audit_days: 120 });
          return { body: { organization_id: "org-a", security_audit_days: 120 } };
        },
      }),
    });
    const user = userEvent.setup();

    const section = await region();
    const days = await within(section).findByLabelText("Keep for (days)");
    await user.clear(days);
    await user.type(days, "120");
    await user.click(within(section).getByRole("button", { name: "Save policy" }));

    expect(await within(section).findByText("120 days")).toBeInTheDocument();
    expect(sent).toEqual([{ security_audit_days: 120 }]);
  });

  it("keeps events for ever when the field is empty", async () => {
    const sent = [];
    renderApp({
      path: "/operations/retention",
      routes: routes({
        "PUT /security/audit/retention": (request) => {
          sent.push(request.body);
          return { body: { organization_id: "org-a", security_audit_days: null } };
        },
      }),
    });
    const user = userEvent.setup();

    const section = await region();
    await user.clear(await within(section).findByLabelText("Keep for (days)"));
    await user.click(within(section).getByRole("button", { name: "Save policy" }));

    await waitFor(() => expect(sent).toEqual([{ security_audit_days: null }]));
  });

  it("runs a cleanup after confirming", async () => {
    const posted = [];
    renderApp({
      path: "/operations/retention",
      routes: routes({
        "POST /security/audit/retention/cleanup": (request) => {
          posted.push(request.body);
          return { body: { organization_id: "org-a", deleted: 4 } };
        },
      }),
    });
    const user = userEvent.setup();

    const section = await region();
    await user.click(await within(section).findByRole("button", { name: "Run cleanup" }));
    expect(
      within(section).getByText("Delete 4 audit events past the policy? This cannot be undone."),
    ).toBeInTheDocument();
    await user.click(within(section).getByRole("button", { name: "Delete events" }));

    await waitFor(() => expect(posted).toEqual([{}]));
  });
});
