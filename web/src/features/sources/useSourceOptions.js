import { useCallback } from "react";

import { useOrganization } from "../../app/useOrganization.js";
import { useResource } from "../../lib/useResource.js";

// The API's largest page. Filters offer the first 100 sources by creation time.
const LIMIT = 100;

/** Sources of the active organization, for filters and pickers. */
export function useSourceOptions() {
  const { tenantApi } = useOrganization();
  const load = useCallback(
    () => tenantApi.get("/sources", { query: { limit: LIMIT } }),
    [tenantApi],
  );
  const { data, error } = useResource(load);
  const sources = data?.items ?? [];
  const names = new Map(sources.map((source) => [source.id, source.name]));
  return { sources, names, error, loaded: data !== null };
}
