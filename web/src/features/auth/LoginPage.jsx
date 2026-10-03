import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";

import { useAuth } from "../../app/useAuth.js";

export function LoginPage() {
  const { login, status } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const target = location.state?.from ?? "/dashboard";

  if (status === "signed_in") return <Navigate to={target} replace />;

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      setPassword("");
      navigate(target, { replace: true });
    } catch (failure) {
      setPassword("");
      setError(failure.message);
      setBusy(false);
    }
  }

  return (
    <main className="shell-main">
      <h1>Sign in</h1>
      <form className="form panel" onSubmit={submit}>
        <label>
          Email
          <input
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>
        <label>
          Password
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" disabled={busy}>
          {busy ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </main>
  );
}
