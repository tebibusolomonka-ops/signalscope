import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AppRoutes } from "./AppRoutes.jsx";

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

describe("AppRoutes", () => {
  it("renders the shell with navigation and a main region", () => {
    renderAt("/dashboard");

    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(nav).toBeInTheDocument();
    for (const label of ["Dashboard", "Organizations", "Users", "Security"]) {
      expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Dashboard" })).toBeInTheDocument();
  });

  it.each([
    ["/organizations", "Organizations"],
    ["/users", "Users"],
    ["/security", "Security"],
    ["/nowhere", "Page not found"],
  ])("routes %s", (path, title) => {
    renderAt(path);
    expect(screen.getByRole("heading", { level: 1, name: title })).toBeInTheDocument();
  });

  it("sends the root path to the dashboard", () => {
    renderAt("/");
    expect(screen.getByRole("heading", { level: 1, name: "Dashboard" })).toBeInTheDocument();
  });

  it("shows the sign in page without the shell", () => {
    renderAt("/login");
    expect(screen.getByRole("heading", { level: 1, name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });
});
