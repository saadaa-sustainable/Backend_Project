"use client";

import { useEffect, useRef, useState } from "react";

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
    if (Date.now() - entry.ts > ttlMs) {
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
  const initial = readCache<T>(key, ttlMs);
  const [data, setData] = useState<T | null>(initial);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState<boolean>(initial === null);
  // Track the latest key we fetched so a fast key-swap (e.g. filter
  // changed twice in a row) doesn't let an in-flight stale response
  // clobber the newer one.
  const activeKeyRef = useRef<string>(key);

  const load = () => {
    activeKeyRef.current = key;
    setLoading(true);
    setError(null);
    fetcher()
      .then((d) => {
        // Bail if the caller re-keyed while our request was in flight.
        if (activeKeyRef.current !== key) return;
        writeCache(key, d);
        setData(d);
        setLoading(false);
      })
      .catch((e: unknown) => {
        if (activeKeyRef.current !== key) return;
        setError(e instanceof Error ? e : new Error(String(e)));
        setLoading(false);
      });
  };

  useEffect(() => {
    const cached = readCache<T>(key, ttlMs);
    if (cached !== null) {
      setData(cached);
      setLoading(false);
      return;
    }
    setData(null);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return { data, error, loading, refetch: load };
}
