import { Navigate, Route, Routes } from "react-router";

import { LoginPage } from "../features/auth/LoginPage.jsx";
import { DashboardPage } from "../features/dashboard/DashboardPage.jsx";
import { AcceptInvitationPage } from "../features/invitations/AcceptInvitationPage.jsx";
import { OrganizationDetailPage } from "../features/organizations/OrganizationDetailPage.jsx";
import { OrganizationsPage } from "../features/organizations/OrganizationsPage.jsx";
import { SecurityPage } from "../features/security/SecurityPage.jsx";
import { UsersPage } from "../features/users/UsersPage.jsx";
import { AppShell } from "./AppShell.jsx";
import { OrganizationProvider } from "./OrganizationContext.jsx";
import { RequireAuth } from "./RequireAuth.jsx";

function NotFound() {
  return <h1>Page not found</h1>;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route
          element={
            <OrganizationProvider>
              <AppShell />
            </OrganizationProvider>
          }
        >
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/organizations" element={<OrganizationsPage />} />
          <Route path="/organizations/:organizationId" element={<OrganizationDetailPage />} />
          <Route path="/users" element={<UsersPage />} />
          <Route path="/accept-invitation" element={<AcceptInvitationPage />} />
          <Route path="/security" element={<SecurityPage />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Route>
    </Routes>
  );
}
