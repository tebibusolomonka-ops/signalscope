import { useState } from "react";
import { Link } from "react-router";

import { useAuth } from "../../app/useAuth.js";
import { PageHeading } from "../../components/PageHeading.jsx";
import { ErrorMessage } from "../../components/Status.jsx";

export function AcceptInvitationPage() {
  const { api } = useAuth();
  const [token, setToken] = useState("");
  const [joined, setJoined] = useState(null);
  const [error, setError] = useState(null);

  async function submit(event) {
    event.preventDefault();
    setError(null);
    try {
      setJoined(await api.post("/organization-invitations/accept", { token: token.trim() }));
      setToken("");
    } catch (failure) {
      setError(failure);
    }
  }

  return (
    <>
      <PageHeading title="Accept an invitation" />
      <form className="form panel" onSubmit={submit}>
        <label>
          Invitation token
          <input
            required
            autoComplete="off"
            value={token}
            onChange={(event) => setToken(event.target.value)}
          />
        </label>
        <ErrorMessage error={error} />
        <button type="submit">Accept invitation</button>
      </form>
      {joined && (
        <p role="status">
          You joined{" "}
          <Link to={`/organizations/${joined.organization.id}`}>{joined.organization.name}</Link>{" "}
          as {joined.role}.
        </p>
      )}
    </>
  );
}
