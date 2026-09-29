import { useCallback, useEffect, useMemo, useState } from "react";

import { createApiClient } from "../lib/api.js";
import { apiBaseUrl } from "../lib/config.js";
import { clearToken, readToken, saveToken } from "../lib/session.js";
import { AuthContext } from "./useAuth.js";

/**
 * Holds the signed in user and an API client that sends their token.
 *
 * On load a stored token is checked with GET /auth/me; a token the API no
 * longer accepts is cleared. The backend decides every permission.
 */
export function AuthProvider({ children, fetchImpl, baseUrl = apiBaseUrl() }) {
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState(() => (readToken() ? "loading" : "signed_out"));

  const api = useMemo(
    () => createApiClient({ baseUrl, getToken: readToken, fetchImpl }),
    [baseUrl, fetchImpl],
  );

  const forget = useCallback(() => {
    clearToken();
    setUser(null);
    setStatus("signed_out");
  }, []);

  useEffect(() => {
    if (status !== "loading") return undefined;
    let active = true;
    api
      .get("/auth/me")
      .then((me) => {
        if (!active) return;
        setUser(me.user);
        setStatus("signed_in");
      })
      .catch(() => {
        if (active) forget();
      });
    return () => {
      active = false;
    };
  }, [api, forget, status]);

  const login = useCallback(
    async (email, password) => {
      const answer = await api.post("/auth/login", { email, password });
      saveToken(answer.access_token);
      setUser(answer.user);
      setStatus("signed_in");
      return answer.user;
    },
    [api],
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } catch {
      // The local session ends even when the API cannot be reached.
    }
    forget();
  }, [api, forget]);

  const value = useMemo(
    () => ({ api, user, status, login, logout, forget }),
    [api, user, status, login, logout, forget],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
