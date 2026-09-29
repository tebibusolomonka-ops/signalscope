import { useCallback, useState } from "react";

import { useAuth } from "../../app/useAuth.js";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { useResource } from "../../lib/useResource.js";

/** A system admin's view of another user's sessions. Never tokens or hashes. */
export function UserSessions({ user }) {
  const { api } = useAuth();
  const path = `/admin/users/${user.id}`;
  const load = useCallback(() => api.get(`${path}/sessions`), [api, path]);
  const { data, error, loading, reload } = useResource(load);
  const [actionError, setActionError] = useState(null);
  const [message, setMessage] = useState(null);

  async function run(action) {
    setActionError(null);
    setMessage(null);
    try {
      const answer = await action();
      if (answer?.revoked_sessions !== undefined) {
        setMessage(`Revoked ${answer.revoked_sessions} sessions.`);
      }
      reload();
    } catch (failure) {
      setActionError(failure);
    }
  }

  return (
    <section className="panel" aria-labelledby="user-sessions-heading">
      <h2 id="user-sessions-heading">Sessions of {user.display_name}</h2>
      {loading && <Loading />}
      <ErrorMessage error={error} />
      <ErrorMessage error={actionError} />
      {message && <p role="status">{message}</p>}
      {data && data.length === 0 && <p className="muted">No sessions.</p>}
      {data && data.length > 0 && (
        <table>
          <thead>
            <tr>
              <th scope="col">Started</th>
              <th scope="col">Last seen</th>
              <th scope="col">Expires</th>
              <th scope="col">Active</th>
              <th scope="col">
                <span className="muted">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {data.map((session) => (
              <tr key={session.session_id}>
                <td>{session.created_at}</td>
                <td>{session.last_seen_at}</td>
                <td>{session.expires_at}</td>
                <td>{session.active ? "Yes" : "No"}</td>
                <td>
                  {session.active && (
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => run(() => api.delete(`${path}/sessions/${session.session_id}`))}
                    >
                      Revoke session started {session.created_at}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <button type="button" onClick={() => run(() => api.post(`${path}/revoke-sessions`))}>
        Revoke all sessions of {user.display_name}
      </button>
    </section>
  );
}
