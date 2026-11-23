import { useCallback } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";

import { DEMO_SCENARIO, useCreateRun } from "@/lib/api/queries";
import { connectRun } from "@/lib/live/store";

/** Create the demo run, subscribe to its live stream and open the Cockpit. */
export function useDemoReplay() {
  const create = useCreateRun();
  const navigate = useNavigate();
  const start = useCallback(async () => {
    try {
      const run = await create.mutateAsync({
        scenario: DEMO_SCENARIO,
        mode: "single",
        runs: 1,
        workers: 1,
      });
      connectRun(run.id);
      toast.success("Demo run started", { description: `${run.name} · ${run.id}` });
      navigate("/cockpit");
    } catch (e) {
      toast.error("Could not start the run", {
        description: e instanceof Error ? e.message : String(e),
      });
    }
  }, [create, navigate]);
  return { start, pending: create.isPending };
}
