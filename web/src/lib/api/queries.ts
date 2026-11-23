import { QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "./client";
import type { Schemas } from "./client";

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
export const DEMO_SCENARIO: Schemas["ScenarioSpec"] = {
  name: "Demo: rumour → denial → earnings miss",
  description:
    "Anonymous acquisition rumour, an official denial two days later, then a real earnings miss.",
  n_agents: 10_000,
  days: 5,
  seed: 0,
  events: [
    {
      id: 0,
      tick: 96 + 44,
      kind: "rumour",
      seeding: "anonymous",
      sentiment: 0.8,
      credibility: 0.2,
      salience: 0.7,
      complexity: 0.2,
      true_impact: 0,
      parent: -1,
      ticker: 0,
      topic: "finance",
      label: "Forum post: Acme in takeover talks",
    },
    {
      id: 1,
      tick: 2 * 96 + 40,
      kind: "statement",
      seeding: "official",
      sentiment: -0.3,
      credibility: 0.9,
      salience: 0.5,
      complexity: 0.2,
      true_impact: 0,
      parent: 0,
      ticker: 0,
      topic: "finance",
      label: "Acme denies takeover reports",
    },
    {
      id: 2,
      tick: 3 * 96 + 39,
      kind: "earnings",
      seeding: "official",
      sentiment: -0.7,
      credibility: 0.95,
      salience: 0.6,
      complexity: 0.5,
      true_impact: -0.05,
      parent: -1,
      ticker: 0,
      topic: "finance",
      label: "Q3 revenue misses estimates",
    },
  ],
};
