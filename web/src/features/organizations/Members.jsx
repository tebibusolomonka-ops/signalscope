import { useCallback, useState } from "react";

import { useAuth } from "../../app/useAuth.js";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { useResource } from "../../lib/useResource.js";

const ORGANIZATION_ROLES = ["owner", "admin", "member", "viewer"];

/** Members with role changes. The API decides who may change what; its 403 is shown. */
export function Members({ organizationId }) {
  const { api } = useAuth();
  const path = `/organizations/${organizationId}/members`;
  const load = useCallback(() => api.get(path), [api, path]);
  const { data, error, loading, reload } = useResource(load);
  const [actionError, setActionError] = useState(null);

  async function run(action) {
    setActionError(null);
    try {
      await action();
      reload();
    } catch (failure) {
      setActionError(failure);
    }
  }

  return (
    <section className="panel" aria-labelledby="members-heading">
      <h2 id="members-heading">Members</h2>
      {loading && <Loading />}
      <ErrorMessage error={error} />
      <ErrorMessage error={actionError} />
      {data && (
        <table>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Email</th>
              <th scope="col">Role</th>
              <th scope="col">
                <span className="muted">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {data.map((member) => (
              <tr key={member.user.id}>
                <td>{member.user.display_name}</td>
                <td>{member.user.email}</td>
                <td>
                  <label>
                    <span className="muted">Role of {member.user.display_name}</span>
                    <select
                      value={member.role}
                      onChange={(event) =>
                        run(() =>
                          api.patch(`${path}/${member.user.id}`, { role: event.target.value }),
                        )
                      }
                    >
                      {ORGANIZATION_ROLES.map((role) => (
                        <option key={role} value={role}>
                          {role}
                        </option>
                      ))}
                    </select>
                  </label>
                </td>
                <td>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => run(() => api.delete(`${path}/${member.user.id}`))}
                  >
                    Remove {member.user.display_name}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <AddMember onAdd={(body) => run(() => api.post(path, body))} />
    </section>
  );
}

function AddMember({ onAdd }) {
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState("member");

  function submit(event) {
    event.preventDefault();
    onAdd({ user_id: userId.trim(), role });
    setUserId("");
  }

  return (
    <form className="form-row" onSubmit={submit}>
      <label>
        User ID
        <input required value={userId} onChange={(event) => setUserId(event.target.value)} />
      </label>
      <label>
        New member role
        <select value={role} onChange={(event) => setRole(event.target.value)}>
          {ORGANIZATION_ROLES.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
      </label>
      <button type="submit">Add member</button>
    </form>
  );
}
