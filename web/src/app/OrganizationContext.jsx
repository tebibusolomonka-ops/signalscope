import { useCallback, useEffect, useMemo, useState } from "react";

import { readOrganization, saveOrganization } from "../lib/activeOrganization.js";
import { createTenantApi } from "../lib/tenantApi.js";
import { useResource } from "../lib/useResource.js";
import { useAuth } from "./useAuth.js";
import { OrganizationContext } from "./useOrganization.js";

/**
 * The organizations of the signed in user and the one the app works in.
 *
 * A remembered choice that is no longer one of the user's organizations is
 * replaced by the first organization, or cleared when there is none.
 */
export function OrganizationProvider({ children }) {
  const { api } = useAuth();
  const load = useCallback(() => api.get("/organizations"), [api]);
  const { data, error, loading, reload } = useResource(load);
  const [selectedId, setSelectedId] = useState(readOrganization);

  const organizations = useMemo(
    () => (data ?? []).map((item) => ({ ...item.organization, role: item.role })),
    [data],
  );
  const active = useMemo(
    () =>
      organizations.find((item) => item.id === selectedId) ?? organizations[0] ?? null,
    [organizations, selectedId],
  );

  useEffect(() => {
    if (data !== null) saveOrganization(active?.id ?? null);
  }, [data, active]);

  const select = useCallback((organizationId) => {
    saveOrganization(organizationId);
    setSelectedId(organizationId);
  }, []);

  const tenantApi = useMemo(
    () => (active ? createTenantApi(api, active.id) : null),
    [api, active],
  );

  const value = useMemo(
    () => ({ organizations, active, select, tenantApi, loading, error, reload }),
    [organizations, active, select, tenantApi, loading, error, reload],
  );
  return <OrganizationContext.Provider value={value}>{children}</OrganizationContext.Provider>;
}
