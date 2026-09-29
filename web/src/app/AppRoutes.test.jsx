import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { signedIn } from "../test/fakeApi.js";
import { renderApp } from "../test/renderApp.jsx";

describe("AppRoutes", () => {
  it("renders the shell with navigation and a main region", async () => {
    renderApp({ routes: signedIn() });

    expect(await screen.findByRole("heading", { level: 1, name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
    for (const label of ["Dashboard", "Organizations", "Users", "Security"]) {
      expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole("main")).toBeInTheDocument();
  });

  it.each([
    ["/organizations", "Organizations"],
    ["/users", "Users"],
    ["/security", "Security"],
    ["/nowhere", "Page not found"],
    ["/", "Dashboard"],
  ])("routes %s", async (path, title) => {
    renderApp({ path, routes: signedIn() });
    expect(await screen.findByRole("heading", { level: 1, name: title })).toBeInTheDocument();
  });
});
