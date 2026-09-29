import { useCallback, useEffect, useState } from "react";

/**
 * Loads data with load() and keeps {data, error, loading}. reload() loads again.
 *
 * load must be stable (for example from useCallback), or it reloads on every
 * render. When load changes, such as after switching organization, the old
 * data is hidden at once, so it is never shown for the new request.
 */
export function useResource(load) {
  const [state, setState] = useState({ load: null, version: -1, data: null, error: null });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let active = true;
    load().then(
      (data) => active && setState({ load, version, data, error: null }),
      (error) => active && setState({ load, version, data: null, error }),
    );
    return () => {
      active = false;
    };
  }, [load, version]);

  const reload = useCallback(() => setVersion((value) => value + 1), []);
  const current = state.load === load;
  return {
    data: current ? state.data : null,
    error: current ? state.error : null,
    loading: !current || state.version !== version,
    reload,
  };
}
