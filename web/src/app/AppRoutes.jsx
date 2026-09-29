import { Navigate, Route, Routes } from "react-router";

import { LoginPage } from "../features/auth/LoginPage.jsx";
import { ClaimDetailPage } from "../features/claims/ClaimDetailPage.jsx";
import { ClaimsPage } from "../features/claims/ClaimsPage.jsx";
import { DashboardPage } from "../features/dashboard/DashboardPage.jsx";
import { EntitiesPage } from "../features/entities/EntitiesPage.jsx";
import { EntityDetailPage } from "../features/entities/EntityDetailPage.jsx";
import { FileImportPage } from "../features/documents/FileImportPage.jsx";
import { DocumentDetailPage } from "../features/documents/DocumentDetailPage.jsx";
import { DocumentsPage } from "../features/documents/DocumentsPage.jsx";
import { EventClusterPage } from "../features/events/EventClusterPage.jsx";
import { TimelinePage } from "../features/events/TimelinePage.jsx";
import { InvestigationDetailPage } from "../features/investigations/InvestigationDetailPage.jsx";
import { InvestigationsPage } from "../features/investigations/InvestigationsPage.jsx";
import { AcceptInvitationPage } from "../features/invitations/AcceptInvitationPage.jsx";
import { OrganizationDetailPage } from "../features/organizations/OrganizationDetailPage.jsx";
import { OrganizationsPage } from "../features/organizations/OrganizationsPage.jsx";
import { SearchPage } from "../features/search/SearchPage.jsx";
import { SecurityPage } from "../features/security/SecurityPage.jsx";
import { SourceComparePage } from "../features/sources/SourceComparePage.jsx";
import { SourceDetailPage } from "../features/sources/SourceDetailPage.jsx";
import { SourcesPage } from "../features/sources/SourcesPage.jsx";
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
            <Route path="/sources" element={<SourcesPage />} />
            <Route path="/sources/compare" element={<SourceComparePage />} />
            <Route path="/sources/:sourceId" element={<SourceDetailPage />} />
            <Route path="/documents" element={<DocumentsPage />} />
            <Route path="/documents/import" element={<FileImportPage />} />
            <Route path="/documents/:documentId" element={<DocumentDetailPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/entities" element={<EntitiesPage />} />
            <Route path="/entities/:entityId" element={<EntityDetailPage />} />
            <Route path="/claims" element={<ClaimsPage />} />
            <Route path="/claims/:claimId" element={<ClaimDetailPage />} />
            <Route path="/events" element={<TimelinePage />} />
            <Route path="/event-clusters/:clusterId" element={<EventClusterPage />} />
            <Route path="/investigations" element={<InvestigationsPage />} />
            <Route path="/investigations/:investigationId" element={<InvestigationDetailPage />} />
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
