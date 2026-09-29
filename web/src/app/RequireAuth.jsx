import { Navigate, Outlet, useLocation } from "react-router";

import { useAuth } from "./useAuth.js";

export function RequireAuth() {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "loading") return <p role="status">Checking your session...</p>;
  if (status !== "signed_in") {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
}
