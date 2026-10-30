import { useEffect, useRef, useState } from "react";

/**
 * Calls `fetcher` now and every `intervalMs`. Pass `deps` for anything the
 * fetcher depends on (a selected period, say): when one changes, the old
 * result is dropped and a fresh fetch starts straight away, so a card never
 * shows one selection's data under another's heading.
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  deps: readonly unknown[] = [],
): { data: T | null; error: string | null } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    let cancelled = false;
    setData(null);

    const tick = async () => {
      try {
        const result = await fetcherRef.current();
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "request failed");
        }
      }
    };

    tick();
    const id = window.setInterval(tick, intervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [intervalMs, ...deps]);

  return { data, error };
}
