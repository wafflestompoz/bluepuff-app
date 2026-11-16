import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

/** Load a server path; reload() to refresh. Skips when path is null. */
export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const reload = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try { setData(await api<T>(path)); setError(null); } catch (e: any) { setError(e.message); } finally { setLoading(false); }
  }, [path]);
  useEffect(() => { setData(null); reload(); }, [reload]);
  return { data, error, loading, reload };
}
