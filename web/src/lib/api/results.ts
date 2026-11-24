/**
 * Shapes of the result endpoints (#18). FastAPI returns these as free-form JSON, so the OpenAPI
 * types are `Record<string, unknown>`; these interfaces describe what the API actually sends.
 */

export interface EventRecord {
  id: number;
  tick: number;
  injected: number;
  kind: string;
  seeding: string;
  sentiment: number;
  credibility: number;
  salience: number;
  complexity: number;
  true_impact: number;
  parent: number;
  item: number;
  label?: string | null;
}

export interface SeriesResponse {
  n_ticks: number;
  every: number;
  tick: number[];
  series: Record<
    | "price"
    | "v_true"
    | "volume"
    | "confidence"
    | "iv"
    | "atm_call"
    | "mm_inventory"
    | "imbalance"
    | "online"
    | "active_items",
    number[]
  >;
  ohlc: [number, number, number, number][];
  events: EventRecord[];
}

export interface QuantilesResponse {
  n_runs: number;
  n_ticks: number;
  quantiles: Record<"0.05" | "0.25" | "0.5" | "0.75" | "0.95", number[]>;
  v_true: number[];
  summary: MonteCarloSummary;
}

export interface MonteCarloSummary {
  n_runs: number;
  n_ticks: number;
  days: number;
  initial_price: number;
  final_price_quantiles: Record<string, number>;
  v_true_final: number;
  p_below_start: number;
  mean_log_return: number;
  var_95: number;
  median_max_drawdown: number;
  mean_volume_per_day: number;
  event_reach_median: Record<string, number>;
  stylized_facts: StylizedSummary;
}

export interface StylizedSummary {
  n_returns: number;
  return_sd: number;
  excess_kurtosis: number | null;
  acf_r: (number | null)[];
  acf_abs_r: (number | null)[];
}

export interface PathsResponse {
  seeds: number[];
  every: number;
  /** Tick of each column (the last column is always the final tick). */
  tick?: number[];
  paths: number[][];
}

export interface Family {
  root: number;
  origin: string;
  kind: string;
  label: string | null;
  members: number;
  aware: number;
  share: number;
  rows: number[][];
}

export interface AwarenessResponse {
  /** item id -> [tick, agents aware] rows while the item was active */
  items: Record<string, [number, number][]>;
  columns: string[];
  platforms: string[];
  categories: string[];
  n_nodes: number;
  platform_sizes: number[] | null;
  category_sizes: number[] | null;
  families: Family[];
}

export interface LineageItem {
  id: number;
  parent: number;
  root: number;
  origin: "event" | "mutation" | "invention" | "price_news";
  sentiment: number;
  credibility: number;
  salience: number;
  born: number;
  is_narrative: boolean;
  topic: string;
  event_id: number;
  kind: string;
  label: string | null;
  final_aware: number;
  total_shares: number;
  retired: number;
}

export interface LineageResponse {
  items: LineageItem[];
  families: Omit<Family, "rows">[];
}

export interface StylizedResponse {
  n_returns: number;
  return_sd: number;
  excess_kurtosis: number | null;
  histogram: { centres: number[]; density: number[]; normal: number[] };
  acf_r: (number | null)[];
  acf_abs_r: (number | null)[];
  band: number;
}

export interface GraphNode {
  id: number;
  index: number;
  category: string;
  influence: number;
  community: number;
  age: number;
  knowledge: number;
  impulsiveness: number;
  wealth: number;
  platforms: string[];
}

export interface GraphResponse {
  n_nodes: number;
  layers: string[];
  nodes: GraphNode[];
  edges: [number, number, string][];
  stats: Record<string, Record<string, unknown>> & { overlap_jaccard?: Record<string, number> };
}

export interface NodeSeenResponse {
  columns: ["tick", "index", "item"];
  rows: [number, number, number][];
}

export interface Trial {
  trial: number;
  params: Record<string, number>;
  rmse: number;
}

export interface CalibrationResult {
  space: Record<string, [number, number]>;
  trials: Trial[];
  best: Record<string, number>;
  best_rmse: number;
  best_path: number[];
  observed: number[];
  sensitivity: Record<string, number>;
  dates: string[];
  meta: Record<string, unknown>;
}

export interface BacktestOrigin {
  origin: number;
  date: string | null;
  close: number;
  actual: number;
  crps_model: number;
  crps_rw: number;
  model_median: number;
  model_q05: number;
  model_q95: number;
  rw_q05: number;
  rw_q95: number;
  events_used: number[];
}

export interface BacktestResult {
  horizon: number;
  origins: BacktestOrigin[];
  mean_crps_model: number;
  mean_crps_rw: number;
  skill: number;
  dates: string[];
  closes: number[];
}

export interface AnalysisResponse<R, P> {
  run: import("./client").RunRecord;
  result: R | null;
  progress: P[];
}
