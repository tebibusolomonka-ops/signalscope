import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";

import { AppRoutes } from "../app/AppRoutes.jsx";
import { AuthProvider } from "../app/AuthContext.jsx";
import { fakeApi } from "./fakeApi.js";

export function renderApp({ path = "/dashboard", routes = {} } = {}) {
  const api = fakeApi(routes);
  const view = render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider fetchImpl={api.fetchImpl} baseUrl="/api">
        <AppRoutes />
      </AuthProvider>
    </MemoryRouter>,
  );
  return { ...view, ...api };
}
