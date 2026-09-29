import { Navigate, Route, Routes } from "react-router";

import { PageHeading } from "../components/PageHeading.jsx";
import { AppShell } from "./AppShell.jsx";

// The feature pages are filled in by later work; each route has its place now.
function Placeholder({ title }) {
  return <PageHeading title={title} />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Placeholder title="Sign in" />} />
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<Placeholder title="Dashboard" />} />
        <Route path="/organizations" element={<Placeholder title="Organizations" />} />
        <Route path="/users" element={<Placeholder title="Users" />} />
        <Route path="/security" element={<Placeholder title="Security" />} />
        <Route path="*" element={<Placeholder title="Page not found" />} />
      </Route>
    </Routes>
  );
}
