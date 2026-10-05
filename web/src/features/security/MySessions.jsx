import { useCallback, useState } from "react";

import { useAuth } from "../../app/useAuth.js";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { useResource } from "../../lib/useResource.js";

/** The signed in user's sessions. Tokens are never shown; the API does not send them. */
export function MySessions() {
  const { api, forget } = useAuth();
  const load = useCallback(() => api.get("/auth/sessions"), [api]);
  const { data, error, loading, reload } = useResource(load);
  const [actionError, setActionError] = useState(null);

  async function revoke(session) {
    setActionError(null);
    try {
      await api.delete(`/auth/sessions/${session.session_id}`);
      reload();
    } catch (failure) {
      setActionError(failure);
    }
  }

  async function logoutAll() {
    setActionError(null);
    try {
      await api.post("/auth/logout-all");
      // Every session ended, this one too.
      forget();
    } catch (failure) {
      setActionError(failure);
    }
  }

  return (
    <section className="panel" aria-labelledby="my-sessions-heading">
      <h2 id="my-sessions-heading">My sessions</h2>
      {loading && <Loading />}
      <ErrorMessage error={error} />
      <ErrorMessage error={actionError} />
      {data && (
        <table>
          <thead>
            <tr>
              <th scope="col">Started</th>
              <th scope="col">Last seen</th>
              <th scope="col">Expires</th>
              <th scope="col">State</th>
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
                <td>{session.effective_expires_at ?? session.expires_at}</td>
                <td>
                  {session.current_session ? "This session" : session.revoked ? "Revoked" : "Active"}
                </td>
                <td>
                  {!session.current_session && !session.revoked && (
                    <button type="button" className="secondary" onClick={() => revoke(session)}>
                      Revoke session started {session.created_at}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <button type="button" onClick={logoutAll}>
        Sign out everywhere
      </button>
    </section>
  );
}
