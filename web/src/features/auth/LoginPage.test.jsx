import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ADMIN, TOKEN, signedIn } from "../../test/fakeApi.js";
import { organizations } from "../../test/organizations.js";
import { renderApp } from "../../test/renderApp.jsx";

const PASSWORD = "a long test password";
const LOGIN = {
  "POST /auth/login": ({ body }) =>
    body.password === PASSWORD
      ? { body: { access_token: TOKEN, token_type: "bearer", expires_at: "x", user: ADMIN } }
      : {
          status: 401,
          body: { error: { code: "unauthenticated", message: "Email or password is not correct." } },
        },
  "POST /auth/logout": { status: 204 },
};

async function signIn(password) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Email"), "admin@example.org");
  await user.type(screen.getByLabelText("Password"), password);
  await user.keyboard("{Enter}");
}

describe("sign in", () => {
  it("redirects a signed out visitor to the sign in page", async () => {
    renderApp({ path: "/organizations", routes: LOGIN });

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("signs in and keeps the token in sessionStorage only", async () => {
    const { calls } = renderApp({ path: "/organizations", routes: LOGIN });
    await screen.findByRole("heading", { name: "Sign in" });

    await signIn(PASSWORD);

    expect(await screen.findByRole("heading", { name: "Organizations" })).toBeInTheDocument();
    expect(screen.getByText("Admin")).toBeInTheDocument();
    expect(sessionStorage.getItem("signalscope.session")).toBe(TOKEN);
    expect(Object.values({ ...localStorage })).not.toContain(TOKEN);
    expect(localStorage.length).toBe(0);
    expect(document.body.innerHTML).not.toContain(TOKEN);
    expect(document.body.innerHTML).not.toContain(PASSWORD);
    expect(calls[0].body).toEqual({ email: "admin@example.org", password: PASSWORD });
  });

  it("shows the API's error for wrong credentials", async () => {
    renderApp({ path: "/login", routes: LOGIN });
    await screen.findByRole("heading", { name: "Sign in" });

    await signIn("wrong password here");

    expect(await screen.findByRole("alert")).toHaveTextContent("Email or password is not correct.");
    expect(sessionStorage.getItem("signalscope.session")).toBeNull();
  });

  it("restores a stored session with GET /auth/me", async () => {
    const { calls } = renderApp({ routes: { ...signedIn(), ...organizations() } });

    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(calls[0].path).toBe("/auth/me");
    expect(calls[0].options.headers.Authorization).toBe(`Bearer ${TOKEN}`);
  });

  it("clears a token the API no longer accepts", async () => {
    sessionStorage.setItem("signalscope.session", "expired-token");
    renderApp({
      routes: {
        "GET /auth/me": {
          status: 401,
          body: { error: { code: "unauthenticated", message: "Authentication is required." } },
        },
      },
    });

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(sessionStorage.getItem("signalscope.session")).toBeNull();
  });

  it("signs out even when the API cannot be reached", async () => {
    const routes = { ...signedIn(), ...organizations() };
    routes["POST /auth/logout"] = () => {
      throw new TypeError("Failed to fetch");
    };
    const user = userEvent.setup();
    renderApp({ routes });
    await screen.findByRole("heading", { name: "Dashboard" });

    await user.click(screen.getByRole("button", { name: "Sign out" }));

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    await waitFor(() => expect(sessionStorage.getItem("signalscope.session")).toBeNull());
  });
});
