import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./client";

/** Minimal data hook: data / error / loading + reload, with optional polling while a condition holds. */
export function useApi<T>(path: string | null, opts: { pollMs?: (data: T | undefined) => number | null } = {}) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const pollRef = useRef(opts.pollMs);
  pollRef.current = opts.pollMs;

  const load = useCallback(async () => {
    if (!path) return undefined;
    try {
      const result = await api<T>(path);
      setData(result);
      setError(null);
      return result;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
      return undefined;
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;
    const tick = async () => {
      const result = await load();
      const next = pollRef.current?.(result);
      if (!cancelled && next) timer = setTimeout(tick, next);
    };
    setLoading(Boolean(path));
    void tick();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [load, path]);

  return { data, error, loading, reload: load };
}
