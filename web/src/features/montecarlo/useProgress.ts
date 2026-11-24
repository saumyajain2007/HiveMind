import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { LiveSocket, streamUrl } from "@/lib/live/socket";
import type { ProgressMessage } from "@/lib/live/types";

/**
 * Follows a running Monte Carlo job's stream: the latest partial quantiles, so the fan fills in
 * while runs finish. When the job ends, the run and its results are refetched.
 */
export function useMonteCarloProgress(runId: string | null | undefined, active: boolean) {
  const qc = useQueryClient();
  const [progress, setProgress] = useState<ProgressMessage | null>(null);
  useEffect(() => {
    if (!runId || !active) return;
    const socket = new LiveSocket({
      url: streamUrl(runId),
      onMessage: (m) => {
        if (m.type === "progress") setProgress(m);
        if (m.type === "done" || m.type === "error") {
          void qc.invalidateQueries({ queryKey: ["run", runId] });
          void qc.invalidateQueries({ queryKey: ["runs"] });
          void qc.invalidateQueries({ queryKey: ["result"] });
        }
      },
    });
    socket.connect();
    return () => socket.close();
  }, [runId, active, qc]);
  return runId && active ? progress : null;
}
