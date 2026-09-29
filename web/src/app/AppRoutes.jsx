import { Navigate, Route, Routes } from "react-router";

import { LoginPage } from "../features/auth/LoginPage.jsx";
import { DashboardPage } from "../features/dashboard/DashboardPage.jsx";
import { AcceptInvitationPage } from "../features/invitations/AcceptInvitationPage.jsx";
import { OrganizationDetailPage } from "../features/organizations/OrganizationDetailPage.jsx";
import { OrganizationsPage } from "../features/organizations/OrganizationsPage.jsx";
import { SecurityPage } from "../features/security/SecurityPage.jsx";
import { UsersPage } from "../features/users/UsersPage.jsx";
import { Placeholder } from "../features/workspace/Placeholder.jsx";
import { AppShell } from "./AppShell.jsx";
import { OrganizationProvider } from "./OrganizationContext.jsx";
import { RequireAuth } from "./RequireAuth.jsx";
import { RequireOrganization } from "./RequireOrganization.jsx";

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
          <Route element={<RequireOrganization />}>
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/sources" element={<Placeholder title="Sources" />} />
            <Route path="/documents" element={<Placeholder title="Documents" />} />
            <Route path="/search" element={<Placeholder title="Search" />} />
            <Route path="/entities" element={<Placeholder title="Entities" />} />
            <Route path="/claims" element={<Placeholder title="Claims" />} />
            <Route path="/events" element={<Placeholder title="Events" />} />
            <Route path="/investigations" element={<Placeholder title="Investigations" />} />
            <Route path="/research" element={<Placeholder title="Research" />} />
          </Route>
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
