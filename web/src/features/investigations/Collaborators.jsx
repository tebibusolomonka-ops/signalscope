import { useCallback, useState } from "react";

import { useAuth } from "../../app/useAuth.js";
import { useOrganization } from "../../app/useOrganization.js";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { useResource } from "../../lib/useResource.js";

const ROLES = ["owner", "editor", "viewer"];

/**
 * The collaborators of an investigation and their roles.
 *
 * Changes are offered to investigation owners and to organization owners
 * and admins; the API decides, also about the last owner. They work on
 * closed investigations too.
 */
export function Collaborators({ investigationId }) {
  const { api, user } = useAuth();
  const { active, can } = useOrganization();
  const load = useCallback(
    () => api.get(`/investigations/${investigationId}/members`),
    [api, investigationId],
  );
  const { data, error, loading, reload } = useResource(load);
  const [actionError, setActionError] = useState(null);
  const mine = data?.find((item) => item.user.id === user.id);
  const manages = can.manage || mine?.role === "owner";

  async function act(send) {
    setActionError(null);
    try {
      await send();
      reload();
    } catch (failure) {
      setActionError(failure);
    }
  }

  const path = (userId) => `/investigations/${investigationId}/members/${userId}`;
  return (
    <section className="panel" aria-labelledby="investigation-collaborators">
      <h2 id="investigation-collaborators">Collaborators</h2>
      {loading && <Loading />}
      <ErrorMessage error={error} />
      {data && data.length === 0 && <p className="muted">No collaborators yet.</p>}
      {data && data.length > 0 && (
        <table>
          <thead>
            <tr>
              <th scope="col">Person</th>
              <th scope="col">Role</th>
              {manages && <th scope="col">Change</th>}
            </tr>
          </thead>
          <tbody>
            {data.map((item) => (
              <tr key={item.user.id}>
                <td>{`${item.user.display_name} (${item.user.email})`}</td>
                <td>
                  {manages ? (
                    <select
                      aria-label={`Role of ${item.user.display_name}`}
                      value={item.role}
                      onChange={(event) =>
                        act(() => api.patch(path(item.user.id), { role: event.target.value }))
                      }
                    >
                      {ROLES.map((role) => (
                        <option key={role} value={role}>
                          {role}
                        </option>
                      ))}
                    </select>
                  ) : (
                    item.role
                  )}
                </td>
                {manages && (
                  <td>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => act(() => api.delete(path(item.user.id)))}
                    >
                      {`Remove ${item.user.display_name}`}
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <ErrorMessage error={actionError} />
      {data && manages && (
        <AddCollaborator
          organizationId={active.id}
          taken={new Set(data.map((item) => item.user.id))}
          onAdd={(body) => act(() => api.post(`/investigations/${investigationId}/members`, body))}
        />
      )}
    </section>
  );
}

function AddCollaborator({ organizationId, taken, onAdd }) {
  const { api } = useAuth();
  const load = useCallback(
    () => api.get(`/organizations/${organizationId}/members`),
    [api, organizationId],
  );
  const { data, error } = useResource(load);
  const candidates = (data ?? []).filter((member) => !taken.has(member.user.id));
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState("viewer");
  const chosen = userId || candidates[0]?.user.id || "";

  function submit(event) {
    event.preventDefault();
    onAdd({ user_id: chosen, role });
    setUserId("");
  }

  return (
    <form className="form-row" onSubmit={submit} aria-label="Add a collaborator">
      <ErrorMessage error={error} />
      {data && candidates.length === 0 && (
        <p className="muted">Every member of this organization is already a collaborator.</p>
      )}
      {candidates.length > 0 && (
        <>
          <label>
            Organization member
            <select value={chosen} onChange={(event) => setUserId(event.target.value)}>
              {candidates.map((member) => (
                <option key={member.user.id} value={member.user.id}>
                  {`${member.user.display_name} (${member.user.email})`}
                </option>
              ))}
            </select>
          </label>
          <label>
            Role
            <select value={role} onChange={(event) => setRole(event.target.value)}>
              {ROLES.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <button type="submit">Add collaborator</button>
        </>
      )}
    </form>
  );
}
