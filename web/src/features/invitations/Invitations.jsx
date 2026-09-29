import { useCallback, useState } from "react";

import { useAuth } from "../../app/useAuth.js";
import { ErrorMessage, Loading } from "../../components/Status.jsx";
import { useResource } from "../../lib/useResource.js";

const INVITATION_ROLES = ["member", "viewer", "admin"];

/**
 * Invitations of one organization.
 *
 * A new invitation token is shown once, from component state only. It is
 * never written to sessionStorage or localStorage, so it is gone on reload.
 */
export function Invitations({ organizationId }) {
  const { api } = useAuth();
  const path = `/organizations/${organizationId}/invitations`;
  const load = useCallback(() => api.get(path), [api, path]);
  const { data, error, loading, reload } = useResource(load);
  const [created, setCreated] = useState(null);
  const [actionError, setActionError] = useState(null);

  async function create(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    setActionError(null);
    try {
      const answer = await api.post(path, { email: values.get("email"), role: values.get("role") });
      setCreated({ email: answer.invitation.email, token: answer.invitation_token });
      form.reset();
      reload();
    } catch (failure) {
      setActionError(failure);
    }
  }

  async function revoke(invitation) {
    setActionError(null);
    try {
      await api.delete(`${path}/${invitation.id}`);
      reload();
    } catch (failure) {
      setActionError(failure);
    }
  }

  return (
    <section className="panel" aria-labelledby="invitations-heading">
      <h2 id="invitations-heading">Invitations</h2>
      {loading && <Loading />}
      <ErrorMessage error={error} />
      <ErrorMessage error={actionError} />
      {created && <OneTimeToken invitation={created} onDone={() => setCreated(null)} />}
      {data && data.length === 0 && <p className="muted">No invitations yet.</p>}
      {data && data.length > 0 && (
        <table>
          <thead>
            <tr>
              <th scope="col">Email</th>
              <th scope="col">Role</th>
              <th scope="col">Status</th>
              <th scope="col">Expires</th>
              <th scope="col">
                <span className="muted">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {data.map((invitation) => (
              <tr key={invitation.id}>
                <td>{invitation.email}</td>
                <td>{invitation.role}</td>
                <td>{invitation.status}</td>
                <td>{new Date(invitation.expires_at).toLocaleString()}</td>
                <td>
                  {invitation.status === "pending" && (
                    <button type="button" className="secondary" onClick={() => revoke(invitation)}>
                      Revoke invitation for {invitation.email}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <form className="form-row" onSubmit={create}>
        <label>
          Invite email
          <input name="email" type="email" required autoComplete="off" />
        </label>
        <label>
          Invite as
          <select name="role" defaultValue="member">
            {INVITATION_ROLES.map((role) => (
              <option key={role} value={role}>
                {role}
              </option>
            ))}
          </select>
        </label>
        <button type="submit">Create invitation</button>
      </form>
    </section>
  );
}

function OneTimeToken({ invitation, onDone }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(invitation.token);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="panel" role="region" aria-label="New invitation token">
      <p>
        Invitation for {invitation.email} created. Copy this token now and share it over a secure
        channel. It is shown only once.
      </p>
      <label>
        Invitation token
        <input readOnly value={invitation.token} onFocus={(event) => event.target.select()} />
      </label>
      <div className="form-row">
        <button type="button" onClick={copy}>
          {copied ? "Copied" : "Copy token"}
        </button>
        <button type="button" className="secondary" onClick={onDone}>
          Done
        </button>
      </div>
    </div>
  );
}
