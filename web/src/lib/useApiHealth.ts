import { useEffect, useState } from "react";

export type ApiHealth =
  | { state: "checking" }
  | { state: "online"; apiVersion: string; engineVersion: string }
  | { state: "offline" };

/** Polls the FastAPI liveness probe. Replaced by TanStack Query in issue #19. */
export function useApiHealth(intervalMs = 10_000): ApiHealth {
  const [health, setHealth] = useState<ApiHealth>({ state: "checking" });

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const r = await fetch("/api/health");
        if (!r.ok) throw new Error(String(r.status));
        const body = (await r.json()) as { api_version: string; engine_version: string };
        if (!cancelled)
          setHealth({
            state: "online",
            apiVersion: body.api_version,
            engineVersion: body.engine_version,
          });
      } catch {
        if (!cancelled) setHealth({ state: "offline" });
      }
    };
    void check();
    const id = setInterval(check, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [intervalMs]);

  return health;
}
