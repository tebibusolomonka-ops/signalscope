import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ADMIN, signedIn } from "../../test/fakeApi.js";
import { renderApp } from "../../test/renderApp.jsx";

function person(index, values = {}) {
  return {
    id: `u-${index}`,
    email: `person${index}@example.org`,
    display_name: `Person ${index}`,
    is_active: true,
    is_system_admin: false,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    ...values,
  };
}

function usersRoutes(people) {
  return {
    ...signedIn(),
    "GET /admin/users": ({ query }) => {
      const text = (query.get("query") ?? "").toLowerCase();
      const active = query.get("is_active");
      const found = people.filter(
        (item) =>
          item.email.includes(text) &&
          (active === null || String(item.is_active) === active),
      );
      const offset = Number(query.get("offset"));
      const limit = Number(query.get("limit"));
      return {
        body: { items: found.slice(offset, offset + limit), total: found.length, limit, offset },
      };
    },
  };
}

describe("users page", () => {
  it("is only for system admins", async () => {
    renderApp({ path: "/users", routes: signedIn({ ...ADMIN, is_system_admin: false }) });

    expect(await screen.findByText("Only system admins can manage users.")).toBeInTheDocument();
  });

  it("lists, searches, filters and pages users", async () => {
    const people = Array.from({ length: 25 }, (_, index) => person(index));
    people[3].is_active = false;
    const { calls } = renderApp({ path: "/users", routes: usersRoutes(people) });
    const user = userEvent.setup();

    expect(await screen.findByText("person0@example.org")).toBeInTheDocument();
    expect(screen.getByText("Showing 1 to 20 of 25")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("Showing 21 to 25 of 25")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Search"), "person3@");
    await user.selectOptions(screen.getByLabelText("Active"), "false");
    await user.click(screen.getByRole("button", { name: "Apply" }));

    expect(await screen.findByText("Showing 1 to 1 of 1")).toBeInTheDocument();
    const last = calls.at(-1);
    expect(last.query.get("query")).toBe("person3@");
    expect(last.query.get("is_active")).toBe("false");
    expect(last.query.get("offset")).toBe("0");
    expect(last.query.has("is_system_admin")).toBe(false);
  });

  it("creates a user and changes activation", async () => {
    const people = [person(1)];
    const routes = {
      ...usersRoutes(people),
      "POST /admin/users": ({ body }) => {
        people.push(person(2, { email: body.email, display_name: body.display_name }));
        return { status: 201, body: people[1] };
      },
      "PATCH /admin/users/u-1/status": ({ body }) => {
        people[0].is_active = body.is_active;
        return { body: people[0] };
      },
    };
    const { calls } = renderApp({ path: "/users", routes });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Deactivate Person 1" }));
    expect(await screen.findByRole("button", { name: "Reactivate Person 1" })).toBeInTheDocument();

    await user.type(screen.getByLabelText("Email"), "new@example.org");
    await user.type(screen.getByLabelText("Display name"), "New Person");
    await user.type(screen.getByLabelText("Password"), "a long enough password");
    await user.click(screen.getByRole("button", { name: "Create user" }));

    expect(await screen.findByText("new@example.org")).toBeInTheDocument();
    expect(calls.find((call) => call.method === "POST").body).toEqual({
      email: "new@example.org",
      display_name: "New Person",
      password: "a long enough password",
      is_system_admin: false,
    });
    await waitFor(() => expect(screen.getByLabelText("Password")).toHaveValue(""));
    expect(document.body.innerHTML).not.toContain("a long enough password");
    expect(document.body.innerHTML).not.toContain("hash");
  });

  it("shows API errors", async () => {
    const routes = {
      ...usersRoutes([person(1)]),
      "POST /admin/users": {
        status: 409,
        body: { error: { code: "conflict", message: "An account with this email already exists." } },
      },
    };
    renderApp({ path: "/users", routes });
    const user = userEvent.setup();

    await screen.findByText("person1@example.org");
    await user.type(screen.getByLabelText("Email"), "person1@example.org");
    await user.type(screen.getByLabelText("Display name"), "Again");
    await user.type(screen.getByLabelText("Password"), "a long enough password");
    await user.click(screen.getByRole("button", { name: "Create user" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "An account with this email already exists.",
    );
  });
});
