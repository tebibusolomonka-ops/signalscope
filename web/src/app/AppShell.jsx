import { NavLink, Outlet } from "react-router";

import { useAuth } from "./useAuth.js";

const LINKS = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/organizations", label: "Organizations" },
  { to: "/users", label: "Users" },
  { to: "/security", label: "Security" },
  { to: "/accept-invitation", label: "Accept invitation" },
];

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
