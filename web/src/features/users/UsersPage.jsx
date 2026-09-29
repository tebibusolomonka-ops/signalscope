import { useCallback, useState } from "react";

import { useAuth } from "../../app/useAuth.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { useResource } from "../../lib/useResource.js";
import { UserSessions } from "./UserSessions.jsx";

const PAGE_SIZE = 20;
const CHOICES = [
  ["", "Any"],
  ["true", "Yes"],
  ["false", "No"],
];

/** System admin user management. The API refuses anyone else; this page only hides it. */
export function UsersPage() {
  const { user } = useAuth();
  if (!user?.is_system_admin) {
    return (
      <>
        <PageHeading title="Users" />
        <p className="muted">Only system admins can manage users.</p>
      </>
    );
  }
  return <UserAdministration />;
}

function UserAdministration() {
  const { api } = useAuth();
  const [filters, setFilters] = useState({ query: "", is_active: "", is_system_admin: "" });
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState(null);
  const [actionError, setActionError] = useState(null);
  const load = useCallback(
    () => api.get("/admin/users", { query: { ...filters, limit: PAGE_SIZE, offset } }),
    [api, filters, offset],
  );
  const { data, error, loading, reload } = useResource(load);

  function applyFilters(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setOffset(0);
    setFilters({
      query: form.get("query").trim(),
      is_active: form.get("is_active"),
      is_system_admin: form.get("is_system_admin"),
    });
  }

  async function setActive(target, active) {
    setActionError(null);
    try {
      await api.patch(`/admin/users/${target.id}/status`, { is_active: active });
      reload();
    } catch (failure) {
      setActionError(failure);
    }
  }

  return (
    <>
      <PageHeading title="Users" />
      <section className="panel" aria-labelledby="users-heading">
        <h2 id="users-heading">All users</h2>
        <form className="form-row" onSubmit={applyFilters} role="search">
          <label>
            Search
            <input name="query" defaultValue={filters.query} />
          </label>
          <label>
            Active
            <select name="is_active" defaultValue={filters.is_active}>
              {CHOICES.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            System admin
            <select name="is_system_admin" defaultValue={filters.is_system_admin}>
              {CHOICES.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <button type="submit">Apply</button>
        </form>
        {loading && <Loading />}
        <ErrorMessage error={error} />
        <ErrorMessage error={actionError} />
        {data && (
          <>
            <table>
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Email</th>
                  <th scope="col">Active</th>
                  <th scope="col">System admin</th>
                  <th scope="col">
                    <span className="muted">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.id}>
                    <td>{item.display_name}</td>
                    <td>{item.email}</td>
                    <td>{item.is_active ? "Yes" : "No"}</td>
                    <td>{item.is_system_admin ? "Yes" : "No"}</td>
                    <td className="form-row">
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => setActive(item, !item.is_active)}
                      >
                        {item.is_active ? "Deactivate" : "Reactivate"} {item.display_name}
                      </button>
                      <button type="button" className="secondary" onClick={() => setSelected(item)}>
                        Sessions of {item.display_name}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted">
              {data.total === 0
                ? "No users match."
                : `Showing ${offset + 1} to ${offset + data.items.length} of ${data.total}`}
            </p>
            <div className="form-row">
              <button
                type="button"
                className="secondary"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                Previous page
              </button>
              <button
                type="button"
                className="secondary"
                disabled={offset + PAGE_SIZE >= data.total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Next page
              </button>
            </div>
          </>
        )}
      </section>
      {selected && <UserSessions key={selected.id} user={selected} />}
      <CreateUser onCreated={reload} />
    </>
  );
}

function CreateUser({ onCreated }) {
  const { api } = useAuth();
  const [error, setError] = useState(null);

  async function submit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    setError(null);
    try {
      await api.post("/admin/users", {
        email: values.get("email"),
        display_name: values.get("display_name"),
        password: values.get("password"),
        is_system_admin: values.get("is_system_admin") === "on",
      });
      form.reset();
      onCreated();
    } catch (failure) {
      setError(failure);
    }
  }

  return (
    <section className="panel" aria-labelledby="create-user-heading">
      <h2 id="create-user-heading">Create a user</h2>
      <form className="form" onSubmit={submit}>
        <label>
          Email
          <input name="email" type="email" required autoComplete="off" />
        </label>
        <label>
          Display name
          <input name="display_name" required autoComplete="off" />
        </label>
        <label>
          Password
          <input name="password" type="password" required minLength={12} autoComplete="new-password" />
        </label>
        <label className="form-row">
          <input name="is_system_admin" type="checkbox" />
          System admin
        </label>
        <ErrorMessage error={error} />
        <button type="submit">Create user</button>
      </form>
    </section>
  );
}
