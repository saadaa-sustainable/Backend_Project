"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { clearAnalyticsCache } from "./api";

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
 *   3. Tab switch back to a cached tab       -> synchronous cache hit, no loading state
 *   4. User calls `refetch()`                -> force fresh fetch, update cache
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

function readCache<T>(key: string, ttlMs: number): T | null {
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
    return entry.data;
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

  useEffect(() => {
    fetcherRef.current = fetcher;
  }, [fetcher]);

  useEffect(() => {
    if (scope.cached !== null) return;
    let cancelled = false;
    fetchShared(scope.key, fetcherRef.current)
      .then((data) => {
        if (!cancelled) setResult({ scope, data, error: null });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setResult({
            scope,
            data: null,
            error: error instanceof Error ? error : new Error(String(error)),
          });
        }
      });
    // This also invalidates a pending response when the next key is a
    // cache hit, and prevents updates after the component unmounts.
    return () => {
      cancelled = true;
    };
  }, [scope]);

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
    data: current ? current.data : scope.cached,
    error: current?.error ?? null,
    loading: current === null && scope.cached === null,
    refetch,
  };
}
