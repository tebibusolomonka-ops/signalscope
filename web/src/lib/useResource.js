import { useCallback, useEffect, useState } from "react";

/**
 * Loads data with load() and keeps {data, error, loading}. reload() loads again.
 * load must be stable (for example from useCallback), or it reloads on every render.
 */
export function useResource(load) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let active = true;
    load().then(
      (data) => active && setState({ data, error: null, loading: false }),
      (error) => active && setState({ data: null, error, loading: false }),
    );
    return () => {
      active = false;
    };
  }, [load, version]);

  const reload = useCallback(() => setVersion((value) => value + 1), []);
  return { ...state, reload };
}
