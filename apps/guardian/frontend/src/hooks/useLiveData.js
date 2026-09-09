import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Fetch-on-mount plus a background refresh, so a dashboard left open reflects new
 * telemetry without anyone pressing reload.
 *
 * Two behaviours matter here and are easy to get wrong:
 *
 * 1. Background refreshes must not flip the page back into its loading state. The
 *    first fetch sets `loading`; every later one sets `refreshing` instead, so the
 *    charts stay on screen and readable while new data is in flight rather than
 *    collapsing to a skeleton every few seconds.
 * 2. A failed refresh must not wipe good data. If Guardian's API blips, we keep the
 *    last successful payload on screen and surface the staleness through
 *    `lastUpdated` -- showing an empty dashboard would read as "nothing is happening
 *    in your system", which is a very different and much worse claim than "I could
 *    not reach the API just now".
 */
/** How many intervals a hidden tab waits between polls (see the interval below). */
const HIDDEN_TAB_SLOWDOWN = 6;

export default function useLiveData(
  fetcher,
  { intervalMs = 10000, enabled = true, refetchKey = null } = {},
) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  // Kept in a ref so changing the fetcher identity every render (the common case,
  // since callers pass an inline arrow) doesn't tear down and restart the interval.
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const load = useCallback(async ({ background } = {}) => {
    if (background) setRefreshing(true);
    try {
      const result = await fetcherRef.current();
      setData(result);
      setError(null);
      setLastUpdated(new Date());
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;

    let cancelled = false;
    const tick = (opts) => {
      if (!cancelled) load(opts);
    };

    tick();

    // A hidden tab is throttled, not stopped. Stopping outright was the first
    // implementation and it was wrong: some embedding contexts (preview panes,
    // in-app browsers) report `hidden` permanently, so a dashboard opened there
    // would sit on stale numbers forever while still looking live. Slowing down
    // addresses the real concern -- a backgrounded tab polling all night -- without
    // that failure mode.
    let sinceLastHiddenPoll = 0;
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') {
        sinceLastHiddenPoll = 0;
        tick({ background: true });
        return;
      }
      sinceLastHiddenPoll += 1;
      if (sinceLastHiddenPoll >= HIDDEN_TAB_SLOWDOWN) {
        sinceLastHiddenPoll = 0;
        tick({ background: true });
      }
    }, intervalMs);

    // Catch up immediately when the user comes back rather than waiting out the
    // remainder of an interval that elapsed while the tab was hidden.
    const onVisible = () => {
      if (document.visibilityState === 'visible') tick({ background: true });
    };
    document.addEventListener('visibilitychange', onVisible);

    return () => {
      cancelled = true;
      clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
    // `refetchKey` lets a caller whose query changed (a filter, a route param) refetch
    // immediately. Without it the fetcher ref would quietly start returning different
    // data while the UI waited out the current interval -- a filter click that appears
    // to do nothing for ten seconds.
  }, [load, intervalMs, enabled, refetchKey]);

  return { data, loading, refreshing, error, lastUpdated, reload: () => load({ background: true }) };
}
