import { useAllTenantItems } from "../../lib/useAllTenantItems.js";

/** Every source of the active organization, for filters and pickers. */
export function useSourceOptions() {
  const { items: sources, error, loaded } = useAllTenantItems("/sources");
  const names = new Map(sources.map((source) => [source.id, source.name]));
  return { sources, names, error, loaded };
}
