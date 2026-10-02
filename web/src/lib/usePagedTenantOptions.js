import { useCallback, useEffect, useMemo, useState } from "react";

import { useOrganization } from "../app/useOrganization.js";

const PAGE_SIZE = 50;

/** Load tenant options a page at a time, resetting them when the request changes. */
export function usePagedTenantOptions(path, filters = {}) {
  const { tenantApi } = useOrganization();
  const filterKey = JSON.stringify(filters);
  const requestKey = `${tenantApi.organizationId}:${path}:${filterKey}`;
  const requestFilters = useMemo(() => JSON.parse(filterKey), [filterKey]);
  const [paging, setPaging] = useState({ key: requestKey, offset: 0 });
  const offset = paging.key === requestKey ? paging.offset : 0;
  const loadKey = `${requestKey}:${offset}`;
  const [state, setState] = useState({
    key: null,
    loadKey: null,
    items: [],
    total: null,
    error: null,
  });

  useEffect(() => {
    let active = true;
    tenantApi.get(path, { query: { ...requestFilters, limit: PAGE_SIZE, offset } }).then(
      (page) => {
        if (!active) return;
        setState((current) => {
          const items = offset === 0 || current.key !== requestKey ? [] : current.items;
          const byId = new Map(items.map((item) => [item.id, item]));
          page.items.forEach((item) => byId.set(item.id, item));
          return {
            key: requestKey,
            loadKey,
            items: [...byId.values()],
            total: page.total,
            error: null,
          };
        });
      },
      (error) =>
        active && setState({ key: requestKey, loadKey, items: [], total: null, error }),
    );
    return () => {
      active = false;
    };
  }, [tenantApi, path, requestFilters, requestKey, loadKey, offset]);

  const loadMore = useCallback(
    () => setPaging({ key: requestKey, offset: offset + PAGE_SIZE }),
    [requestKey, offset],
  );
  const current = state.key === requestKey;
  const items = current ? state.items : [];
  const total = current ? state.total : null;
  return {
    items,
    total,
    error: current ? state.error : null,
    loading: state.loadKey !== loadKey,
    loadMore,
    hasMore: total !== null && items.length < total,
  };
}
