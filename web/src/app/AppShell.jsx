import { NavLink, Outlet } from "react-router";

import { useAuth } from "./useAuth.js";
import { useOrganization } from "./useOrganization.js";

// Content of the active organization.
const CONTENT_LINKS = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/sources", label: "Sources" },
  { to: "/documents", label: "Documents" },
  { to: "/search", label: "Search" },
  { to: "/entities", label: "Entities" },
  { to: "/claims", label: "Claims" },
  { to: "/events", label: "Events" },
  { to: "/investigations", label: "Investigations" },
  { to: "/research", label: "Research" },
];

const ADMIN_LINKS = [
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

function NavList({ label, links }) {
  return (
    <ul className="nav-list" aria-label={label}>
      {links.map((link) => (
        <li key={link.to}>
          <NavLink to={link.to}>{link.label}</NavLink>
        </li>
      ))}
    </ul>
  );
}

export function AppShell() {
  const { user, logout } = useAuth();
  return (
    <div className="shell">
      <header className="shell-header">
        <span className="brand">SignalScope Admin</span>
        <OrganizationPicker />
        <span className="muted">{user?.display_name}</span>
        <button type="button" className="secondary" onClick={logout}>
          Sign out
        </button>
        <nav aria-label="Main" className="shell-nav">
          <NavList label="Content" links={CONTENT_LINKS} />
          <NavList label="Administration" links={ADMIN_LINKS} />
        </nav>
      </header>
      <main className="shell-main">
        <Outlet />
      </main>
    </div>
  );
}
