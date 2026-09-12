import { useCallback, useEffect, useRef, useState } from 'react';

const HIDDEN_TAB_SLOWDOWN = 6;

/** Poll without overlapping reads or allowing a previous query to replace new data.
 * Fetchers may consume the supplied AbortSignal. Transient failures retain the
 * latest successful data; callers distinguish authoritative 404s from outages.
 */
export default function useLiveData(
  fetcher,
  { intervalMs = 10000, enabled = true, refetchKey = null } = {},
) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const fetcherRef = useRef(fetcher);
  const generationRef = useRef(0);
  const inFlightRef = useRef(null);
  fetcherRef.current = fetcher;

  const load = useCallback(async ({ background } = {}) => {
    const generation = generationRef.current;
    if (inFlightRef.current?.generation === generation) return;
    const request = { generation, controller: new AbortController() };
    inFlightRef.current = request;
    const current = () => generationRef.current === generation && inFlightRef.current === request;
    if (background) setRefreshing(true);
    try {
      const result = await fetcherRef.current({ signal: request.controller.signal });
      if (!current()) return;
      setData(result);
      setError(null);
      setLastUpdated(new Date());
    } catch (failure) {
      if (current()) setError(failure);
    } finally {
      if (current()) {
        inFlightRef.current = null;
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    generationRef.current += 1;
    if (!enabled) return undefined;
    setLoading(true);
    setError(null);
    let cancelled = false;
    const tick = (options) => {
      if (!cancelled) load(options);
    };
    tick();

    let sinceLastHiddenPoll = 0;
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') {
        sinceLastHiddenPoll = 0;
        tick({ background: true });
      } else if (++sinceLastHiddenPoll >= HIDDEN_TAB_SLOWDOWN) {
        sinceLastHiddenPoll = 0;
        tick({ background: true });
      }
    }, intervalMs);
    const onVisible = () => {
      if (document.visibilityState === 'visible') tick({ background: true });
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      cancelled = true;
      generationRef.current += 1;
      inFlightRef.current?.controller.abort();
      inFlightRef.current = null;
      clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [load, intervalMs, enabled, refetchKey]);

  return { data, loading, refreshing, error, lastUpdated, reload: () => load({ background: true }) };
}
