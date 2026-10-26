"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { clearAnalyticsCache } from "./api";
import { useAnalyticsSectionVisible } from "./analyticsSectionVisibility";

/**
 * sessionStorage-backed cache for API fetches. Survives page refresh
 * (F5 / Ctrl+F5) but clears when the browser tab is closed. Keyed on
 * a caller-supplied string that MUST include any query parameters
 * that affect the response (window, sort, filter, etc.) -- otherwise
 * stale data flashes when the user tweaks a control.
 *
 * Behavior:
 *   1. First mount, cache hit + not expired  -> render cached data immediately, no network
 *   2. First mount, cache miss or expired    -> fetch, render on arrival, populate cache
 *   3. Tab switch back to a cached tab       -> instant data; refresh if expired
 *   4. User calls `refetch()`                -> force fresh fetch, update cache
 *   5. Visible section reaches expiry       -> refresh without hiding its data
 *
 * TTL defaults to 5 minutes -- long enough that browsing between
 * tabs feels instant, short enough that a merchant checking numbers
 * after a data refresh gets fresh values within one work-break.
 */

const DEFAULT_TTL_MS = 5 * 60 * 1000;
const inFlight = new Map<string, Promise<unknown>>();

interface CacheEntry<T> {
  data: T;
  ts: number;
}

function readCache<T>(key: string, ttlMs: number): CacheEntry<T> | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(key);
    if (!raw) return null;
    const entry = JSON.parse(raw) as CacheEntry<T>;
    if (!entry || typeof entry.ts !== "number" || !Number.isFinite(entry.ts) || !("data" in entry)) {
      return null;
    }
    if (Date.now() - entry.ts >= ttlMs) {
      window.sessionStorage.removeItem(key);
      return null;
    }
    return entry;
  } catch {
    return null;
  }
}

function writeCache<T>(key: string, data: T): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(key, JSON.stringify({ data, ts: Date.now() } satisfies CacheEntry<T>));
  } catch {
    // Quota exceeded or private-mode: cache silently disabled, fetch
    // still works fine. Not worth surfacing to the user.
  }
}

function fetchShared<T>(key: string, fetcher: () => Promise<T>): Promise<T> {
  const pending = inFlight.get(key);
  if (pending) return pending as Promise<T>;

  // Share requests across components and React Strict Mode remounts. An
  // explicit refetch can replace this request, so only its successor may
  // populate the cache after that point.
  const request = Promise.resolve()
    .then(fetcher)
    .then((data) => {
      if (inFlight.get(key) === request) writeCache(key, data);
      return data;
    })
    .finally(() => {
      if (inFlight.get(key) === request) inFlight.delete(key);
    });
  inFlight.set(key, request);
  return request;
}

export interface UseCachedFetchResult<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  refetch: () => void;
}

/**
 * @param key       Full cache key including any params that scope the response.
 *                  Example: `dashboard/kpis` or `cpis-utm|window=30d|sort=roas`.
 * @param fetcher   Fetch function that returns the payload. Called only on
 *                  cache miss / expiry / explicit refetch.
 * @param ttlMs     TTL for cache entry in ms (default 5 minutes).
 */
export function useCachedFetch<T>(
  key: string,
  fetcher: () => Promise<T>,
  ttlMs: number = DEFAULT_TTL_MS,
): UseCachedFetchResult<T> {
  const visible = useAnalyticsSectionVisible();
  const [revision, setRevision] = useState(0);
  // Parse sessionStorage only when the request changes, rather than on
  // every render of a dashboard tile.
  const scope = useMemo(
    () => ({ key, revision, cached: readCache<T>(key, ttlMs) }),
    [key, ttlMs, revision],
  );
  const [result, setResult] = useState<{
    scope: typeof scope;
    data: T | null;
    error: Error | null;
  } | null>(null);
  const fetcherRef = useRef(fetcher);
  // Analytics tabs stay mounted while hidden. Track the age of the
  // rendered response independently of mounts and unrelated rerenders.
  const lastSuccess = useRef<{ scope: typeof scope; ts: number } | null>(null);
  const failedScope = useRef<typeof scope | null>(null);

  useEffect(() => {
    fetcherRef.current = fetcher;
  }, [fetcher]);

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    let pending = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    function schedule(ts: number) {
      clearTimeout(timer);
      timer = setTimeout(refreshIfStale, Math.max(1000, ts + ttlMs - Date.now()));
    }

    function refreshIfStale() {
      if (cancelled || pending || document.visibilityState === "hidden"
        || failedScope.current === scope) return;
      const loadedAt = lastSuccess.current?.scope === scope
        ? lastSuccess.current.ts : scope.cached?.ts;
      if (loadedAt !== undefined && Date.now() - loadedAt < ttlMs) {
        schedule(loadedAt);
        return;
      }

      pending = true;
      // Another reader may have refreshed this key while we were hidden.
      const cached = readCache<T>(scope.key, ttlMs);
      const request = cached !== null ? Promise.resolve(cached)
        : fetchShared(scope.key, fetcherRef.current)
          .then((data) => ({ data, ts: Date.now() }));
      request.then((entry) => {
        if (cancelled) return;
        lastSuccess.current = { scope, ts: entry.ts };
        setResult({ scope, data: entry.data, error: null });
        schedule(entry.ts);
      }).catch((error: unknown) => {
        if (cancelled) return;
        // Leave failures to the existing Retry control; focus and timers
        // must not silently retry a failed connection.
        failedScope.current = scope;
        setResult({
          scope,
          data: null,
          error: error instanceof Error ? error : new Error(String(error)),
        });
      }).finally(() => {
        pending = false;
      });
    }

    refreshIfStale();
    window.addEventListener("focus", refreshIfStale);
    document.addEventListener("visibilitychange", refreshIfStale);
    // This also invalidates a pending response when the next key is a
    // cache hit, and prevents updates after the component unmounts.
    return () => {
      cancelled = true;
      clearTimeout(timer);
      window.removeEventListener("focus", refreshIfStale);
      document.removeEventListener("visibilitychange", refreshIfStale);
    };
  }, [scope, visible, ttlMs]);

  const refetch = useCallback(() => {
    try {
      window.sessionStorage.removeItem(key);
    } catch {
      // Fetching remains available when browser storage is disabled.
    }
    inFlight.delete(key);
    clearAnalyticsCache();
    setRevision((value) => value + 1);
  }, [key]);

  const current = result?.scope === scope ? result : null;
  return {
    data: current ? current.data : scope.cached?.data ?? null,
    error: current?.error ?? null,
    loading: current === null && scope.cached === null,
    refetch,
  };
}
