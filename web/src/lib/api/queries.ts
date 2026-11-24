import { QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "./client";
import type { Schemas } from "./client";
import type * as E from "./experiments";
import type * as R from "./results";
import { DEMO } from "@/features/builder/presets";

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { staleTime: 10_000, retry: 1, refetchOnWindowFocus: false },
    },
  });
}

export const keys = {
  health: ["health"] as const,
  configSchema: ["config", "schema"] as const,
  configDefaults: ["config", "defaults"] as const,
  runs: (status?: string) => ["runs", status ?? "all"] as const,
  run: (id: string) => ["run", id] as const,
  scenarios: ["scenarios"] as const,
};

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: async () => unwrap(await api.GET("/api/v1/health")),
    refetchInterval: 10_000,
    retry: false,
  });
}

export function useConfigSchema() {
  return useQuery({
    queryKey: keys.configSchema,
    queryFn: async () => unwrap(await api.GET("/api/v1/config/schema")),
    staleTime: Infinity,
  });
}

export function useRuns(status?: Schemas["RunStatus"]) {
  return useQuery({
    queryKey: keys.runs(status),
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/runs", { params: { query: { limit: 100, status } } })),
    refetchInterval: 5_000,
  });
}

export function useRun(id: string | null) {
  return useQuery({
    queryKey: keys.run(id ?? ""),
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/runs/{run_id}", { params: { path: { run_id: id ?? "" } } })),
    enabled: Boolean(id),
  });
}

export function useCreateRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Schemas["RunCreate"]) =>
      unwrap(await api.POST("/api/v1/runs", { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runs"] }),
  });
}

/** The scripted demo from HANDOFF §4 M4: rumour (day 1), denial (day 3), earnings miss (day 4). */
export const DEMO_SCENARIO: Schemas["ScenarioSpec"] = DEMO;

// ----------------------------------------------------------------------------- run control

export function useCancelRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.POST("/api/v1/runs/{run_id}/cancel", { params: { path: { run_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runs"] }),
  });
}

export function useDeleteRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const res = await api.DELETE("/api/v1/runs/{run_id}", { params: { path: { run_id: id } } });
      if (!res.response.ok) unwrap(res);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runs"] }),
  });
}

// ----------------------------------------------------------------------------- scenarios

export function useScenarios() {
  return useQuery({
    queryKey: keys.scenarios,
    queryFn: async () => unwrap(await api.GET("/api/v1/scenarios")),
  });
}

export function useConfigDefaults() {
  return useQuery({
    queryKey: keys.configDefaults,
    queryFn: async () => unwrap(await api.GET("/api/v1/config/defaults")),
    staleTime: Infinity,
  });
}

export function useSaveScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, spec }: { id?: string | null; spec: Schemas["ScenarioSpec"] }) =>
      id
        ? unwrap(
            await api.PUT("/api/v1/scenarios/{scenario_id}", {
              params: { path: { scenario_id: id } },
              body: spec,
            }),
          )
        : unwrap(await api.POST("/api/v1/scenarios", { body: spec })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.scenarios }),
  });
}

export function useParseHeadlines() {
  return useMutation({
    mutationFn: async (body: Schemas["ParseRequest"]) =>
      unwrap(await api.POST("/api/v1/events/parse", { body })),
  });
}

// ----------------------------------------------------------------------------- results

type ResultPath =
  | "/api/v1/runs/{run_id}/series"
  | "/api/v1/runs/{run_id}/quantiles"
  | "/api/v1/runs/{run_id}/paths"
  | "/api/v1/runs/{run_id}/awareness"
  | "/api/v1/runs/{run_id}/lineage"
  | "/api/v1/runs/{run_id}/stylized-facts"
  | "/api/v1/runs/{run_id}/graph"
  | "/api/v1/runs/{run_id}/node-seen";

/** Finished runs never change, so their results are cached for the session. */
function useResult<T>(
  path: ResultPath,
  id: string | null | undefined,
  query: Record<string, string | number> = {},
) {
  return useQuery({
    queryKey: ["result", path, id ?? "", query],
    queryFn: async (): Promise<T> => {
      const res = await api.GET(path, {
        params: { path: { run_id: id ?? "" }, query: query as never },
      });
      return unwrap(res) as unknown as T;
    },
    enabled: Boolean(id),
    staleTime: Infinity,
    retry: false,
  });
}

export const useSeries = (id?: string | null, every = 1) =>
  useResult<R.SeriesResponse>("/api/v1/runs/{run_id}/series", id, { every });
export const useQuantiles = (id?: string | null) =>
  useResult<R.QuantilesResponse>("/api/v1/runs/{run_id}/quantiles", id);
export const usePaths = (id?: string | null, sample = 20, every = 2) =>
  useResult<R.PathsResponse>("/api/v1/runs/{run_id}/paths", id, { sample, every });
export const useAwareness = (id?: string | null) =>
  useResult<R.AwarenessResponse>("/api/v1/runs/{run_id}/awareness", id, { every: 2 });
export const useLineage = (id?: string | null) =>
  useResult<R.LineageResponse>("/api/v1/runs/{run_id}/lineage", id);
export const useStylized = (id?: string | null) =>
  useResult<R.StylizedResponse>("/api/v1/runs/{run_id}/stylized-facts", id);
export const useGraph = (id?: string | null, layer = "all", sample = 1200) =>
  useResult<R.GraphResponse>("/api/v1/runs/{run_id}/graph", id, { layer, sample });
export const useNodeSeen = (id?: string | null) =>
  useResult<R.NodeSeenResponse>("/api/v1/runs/{run_id}/node-seen", id);

// ----------------------------------------------------------------------------- analysis

export function useDatasets() {
  return useQuery({
    queryKey: ["datasets"],
    queryFn: async () => unwrap(await api.GET("/api/v1/data")),
  });
}

export function useDataset(id: string | null | undefined) {
  return useQuery({
    queryKey: ["dataset", id ?? ""],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/data/{dataset_id}", { params: { path: { dataset_id: id ?? "" } } }),
      ),
    enabled: Boolean(id),
    staleTime: Infinity,
  });
}

export function useUploadDataset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Schemas["DatasetUpload"]) =>
      unwrap(await api.POST("/api/v1/data/upload", { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["datasets"] }),
  });
}

export function useCreateCalibration() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Schemas["CalibrationCreate"]) =>
      unwrap(await api.POST("/api/v1/calibrations", { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runs"] }),
  });
}

export function useCreateBacktest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Schemas["BacktestCreate"]) =>
      unwrap(await api.POST("/api/v1/backtests", { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runs"] }),
  });
}

export function useCalibration(id: string | null | undefined) {
  return useQuery({
    queryKey: ["calibration", id ?? ""],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/calibrations/{run_id}", { params: { path: { run_id: id ?? "" } } }),
      ) as unknown as R.AnalysisResponse<R.CalibrationResult, R.Trial>,
    enabled: Boolean(id),
    refetchInterval: (q) => (q.state.data?.result ? false : 1_500),
  });
}

export function useBacktest(id: string | null | undefined) {
  return useQuery({
    queryKey: ["backtest", id ?? ""],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/backtests/{run_id}", { params: { path: { run_id: id ?? "" } } }),
      ) as unknown as R.AnalysisResponse<R.BacktestResult, R.BacktestOrigin>,
    enabled: Boolean(id),
    refetchInterval: (q) => (q.state.data?.result ? false : 1_500),
  });
}

// ----------------------------------------------------------------------------- real-data experiments

export function useExperiments() {
  return useQuery({
    queryKey: ["experiments"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/experiments")) as unknown as E.ExperimentListItem[],
    staleTime: Infinity,
  });
}

export function useExperiment(ticker: string | null | undefined) {
  return useQuery({
    queryKey: ["experiment", ticker ?? ""],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/experiments/{ticker}", {
          params: { path: { ticker: ticker ?? "" } },
        }),
      ) as unknown as E.ExperimentResults,
    enabled: Boolean(ticker),
    staleTime: Infinity,
  });
}

export function useStrategy(ticker: string | null | undefined) {
  return useQuery({
    queryKey: ["strategy", ticker ?? ""],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/experiments/{ticker}/strategy", {
          params: { path: { ticker: ticker ?? "" } },
        }),
      ) as unknown as E.StrategyDoc,
    enabled: Boolean(ticker),
    staleTime: Infinity,
  });
}
