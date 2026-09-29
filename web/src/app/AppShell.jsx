import { NavLink, Outlet } from "react-router";

const LINKS = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/organizations", label: "Organizations" },
  { to: "/users", label: "Users" },
  { to: "/security", label: "Security" },
];

export function AppShell() {
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
      </header>
      <main className="shell-main">
        <Outlet />
      </main>
    </div>
  );
}
