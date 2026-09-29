import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { TOKEN, signedIn } from "../test/fakeApi.js";
import { renderApp } from "../test/renderApp.jsx";

const KEY = "signalscope.organization";
const HARBOUR = { id: "org-a", name: "Harbour Watch", slug: "harbour" };
const RIVER = { id: "org-b", name: "River Desk", slug: "river" };

function routes(organizations) {
  return {
    ...signedIn(),
    "GET /organizations": {
      body: organizations.map((organization) => ({ organization, role: "viewer" })),
    },
  };
}

describe("active organization", () => {
  it("loads the organizations and picks the first one", async () => {
    renderApp({ path: "/users", routes: routes([HARBOUR, RIVER]) });

    const picker = await screen.findByLabelText("Active organization");
    expect(picker).toHaveValue("org-a");
    await waitFor(() => expect(sessionStorage.getItem(KEY)).toBe("org-a"));
  });

  it("restores the choice from sessionStorage and switches", async () => {
    sessionStorage.setItem(KEY, "org-b");
    renderApp({ path: "/users", routes: routes([HARBOUR, RIVER]) });
    const user = userEvent.setup();

    const picker = await screen.findByLabelText("Active organization");
    expect(picker).toHaveValue("org-b");
    await user.selectOptions(picker, "org-a");

    expect(picker).toHaveValue("org-a");
    expect(sessionStorage.getItem(KEY)).toBe("org-a");
    expect(sessionStorage.getItem("signalscope.session")).toBe(TOKEN);
    expect(localStorage.length).toBe(0);
  });

  it("replaces a choice that is no longer one of the user's organizations", async () => {
    sessionStorage.setItem(KEY, "org-gone");
    renderApp({ path: "/users", routes: routes([RIVER]) });

    expect(await screen.findByLabelText("Active organization")).toHaveValue("org-b");
    await waitFor(() => expect(sessionStorage.getItem(KEY)).toBe("org-b"));
  });

  it("shows when the user has no organization", async () => {
    sessionStorage.setItem(KEY, "org-gone");
    renderApp({ path: "/users", routes: routes([]) });

    expect(await screen.findByText("No organization")).toBeInTheDocument();
    await waitFor(() => expect(sessionStorage.getItem(KEY)).toBeNull());
  });

  it("never puts the token in the page or a URL", async () => {
    const { calls } = renderApp({ path: "/users", routes: routes([HARBOUR]) });

    await screen.findByLabelText("Active organization");

    expect(document.body.innerHTML).not.toContain(TOKEN);
    for (const call of calls) {
      expect(call.path).not.toContain(TOKEN);
      expect(call.query.has("organization_id")).toBe(false);
    }
  });
});
