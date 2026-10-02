import { useMemo, useState } from "react";

import { usePagedTenantOptions } from "../../lib/usePagedTenantOptions.js";

/** Sources of the active organization, for filters and pickers. */
export function useSourceOptions() {
  const [query, setQuery] = useState("");
  const filters = useMemo(() => (query.trim() ? { query: query.trim() } : {}), [query]);
  const options = usePagedTenantOptions("/sources", filters);
  const names = new Map(options.items.map((source) => [source.id, source.name]));
  return { ...options, sources: options.items, names, query, setQuery, loaded: !options.loading };
}
