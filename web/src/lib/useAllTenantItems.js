import { useCallback } from "react";

import { useOrganization } from "../app/useOrganization.js";
import { useResource } from "./useResource.js";

// One request per page; the loop stops once every item has been fetched.
const PAGE = 100;
// A ceiling so a wrong total can never loop forever.
const MAX_ITEMS = 10000;

/**
 * Every item of a paged tenant list, fetched page by page.
 *
 * Pickers and filters need the whole list, not just the first page. Each
 * request is scoped to the active organization; when the organization changes
 * the request changes, so the old items are dropped and never shown for the
 * new one.
 */
export function useAllTenantItems(path, query) {
  const { tenantApi } = useOrganization();
  // A stable key so the loader is only rebuilt when the query really changes.
  const key = JSON.stringify(query ?? {});
  const load = useCallback(async () => {
    const extra = JSON.parse(key);
    const items = [];
    let total = Infinity;
    while (items.length < total && items.length < MAX_ITEMS) {
      const result = await tenantApi.get(path, {
        query: { ...extra, limit: PAGE, offset: items.length },
      });
      items.push(...result.items);
      total = result.total;
      if (result.items.length === 0) break;
    }
    return items;
  }, [tenantApi, path, key]);
  const { data, error } = useResource(load);
  return { items: data ?? [], error, loaded: data !== null };
}
