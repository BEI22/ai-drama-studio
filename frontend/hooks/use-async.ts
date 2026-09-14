"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";

export interface AsyncState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

/**
 * Minimal data-fetching hook with explicit loading / error / empty handling.
 *
 * Phase 1 keeps this dependency-free on purpose; it can be swapped for TanStack
 * Query in a later phase without touching call sites.
 */
export function useAsync<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  // Keep the latest fetcher without forcing callers to memoise it.
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetcherRef
      .current()
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        setError(
          caught instanceof ApiError
            ? caught
            : new ApiError(caught instanceof Error ? caught.message : "未知错误", {
                code: "UNKNOWN",
                status: 0,
                requestId: null,
              }),
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  return { data, error, loading, reload };
}
