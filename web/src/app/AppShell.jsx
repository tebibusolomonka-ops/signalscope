import { NavLink, Outlet } from "react-router";

import { useAuth } from "./useAuth.js";
import { useOrganization } from "./useOrganization.js";

const LINKS = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/organizations", label: "Organizations" },
  { to: "/users", label: "Users" },
  { to: "/security", label: "Security" },
  { to: "/accept-invitation", label: "Accept invitation" },
];

function OrganizationPicker() {
  const { organizations, active, select, loading, error } = useOrganization();
  if (loading) return <span className="muted">Loading organizations...</span>;
  if (error) return <span className="muted">Organizations could not be loaded.</span>;
  if (!active) return <span className="muted">No organization</span>;
  return (
    <label className="picker">
      Active organization
      <select value={active.id} onChange={(event) => select(event.target.value)}>
        {organizations.map((organization) => (
          <option key={organization.id} value={organization.id}>
            {organization.name}
          </option>
        ))}
      </select>
    </label>
  );
}

export function AppShell() {
  const { user, logout } = useAuth();
  return (
    <div className="shell">
      <header className="shell-header">
        <span className="brand">SignalScope Admin</span>
        <nav aria-label="Main">
          <ul className="nav-list">
            {LINKS.map((link) => (
              <li key={link.to}>
                <NavLink to={link.to}>{link.label}</NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <OrganizationPicker />
        <span className="muted">{user?.display_name}</span>
        <button type="button" className="secondary" onClick={logout}>
          Sign out
        </button>
      </header>
      <main className="shell-main">
        <Outlet />
      </main>
    </div>
  );
}
