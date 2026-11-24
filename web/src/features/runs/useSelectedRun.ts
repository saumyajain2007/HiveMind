import { useSearchParams } from "react-router";

import type { RunRecord } from "@/lib/api/client";
import { useRuns } from "@/lib/api/queries";

type Mode = RunRecord["mode"];

/**
 * The run a results page shows: `?run=<id>` if given, otherwise the newest finished run of one
 * of `modes`. Returns the id plus the candidate list for the picker.
 */
export function useSelectedRun(modes: Mode[]) {
  const [params, setParams] = useSearchParams();
  const runs = useRuns();
  const candidates = (runs.data?.items ?? []).filter((r) => modes.includes(r.mode));
  const wanted = params.get("run");
  const finished = candidates.filter((r) => r.status === "done" || r.status === "cancelled");
  const id = wanted ?? finished[0]?.id ?? null;
  const run = candidates.find((r) => r.id === id) ?? null;
  return {
    id,
    run,
    candidates,
    loading: runs.isLoading,
    select: (next: string) =>
      setParams((p) => {
        p.set("run", next);
        return p;
      }),
  };
}
