/**
 * Real-data experiments (`python -m marketsim.experiment <TICKER>`), served by
 * `/api/v1/experiments`. FastAPI sends them as free-form JSON; these interfaces describe it.
 */

export const MODELS = ["random_walk", "event_random_walk", "abm_raw", "abm", "abm_oracle"] as const;
export type ModelKey = (typeof MODELS)[number];

export const MODEL_LABEL: Record<ModelKey, string> = {
  random_walk: "Random walk",
  event_random_walk: "Event-aware random walk",
  abm_raw: "Agent model, raw",
  abm: "Agent model, recalibrated",
  abm_oracle: "Agent model, oracle",
};

export interface ModelStats {
  mean_crps_pct: number;
  skill_vs_random_walk: number;
  coverage_90: number;
  direction_accuracy: number;
  brier_up: number;
}

export type SliceStats = { n: number } & Partial<Record<ModelKey, ModelStats>>;

export interface Forecast {
  crps: number;
  median: number;
  q05: number;
  q95: number;
  p_up: number;
}

export type OriginRow = {
  origin: string;
  target: string;
  close: number;
  actual: number;
  actual_return: number;
  earnings_in_horizon: boolean;
  events_known: number;
} & Record<ModelKey, Forecast>;

export interface ImpactMetrics {
  n: number;
  accuracy: number;
  majority_accuracy: number;
  log_loss: number;
  base_rate_log_loss: number;
  direction_hit_rate: number;
  n_moves: number;
  size_mae_log: number;
  constant_size_mae_log: number;
  size_corr: number;
}

export interface Recalibration {
  shrink: number;
  spread: number;
  vol_weight: number;
  train_crps: number;
  raw_train_crps: number;
}

export interface ImpactEvent {
  date: string;
  released: string;
  form: string;
  items: string[];
  group: string;
  actual: number;
  p_down: number;
  p_flat: number;
  p_up: number;
  size: number;
  expected: number;
}

export interface ExperimentResults {
  ticker: string;
  name: string;
  period: { train: [string, string]; test: [string, string] };
  events: { total: number; labelled: number; train: number; test: number };
  impact_model: {
    l2: number;
    n_train: number;
    n_test: number;
    test: ImpactMetrics;
    test_earnings?: ImpactMetrics;
    size_weights: Record<string, number>;
    direction_weights: Record<string, number>;
    events?: ImpactEvent[];
    jump_scale?: number;
  };
  simulation: {
    params: Record<string, number>;
    grid: { params: Record<string, number>; mean_crps: number }[];
    recalibration?: Record<string, Recalibration>;
  };
  backtest: Record<
    string,
    {
      summary: { all: SliceStats; earnings_in_horizon: SliceStats; no_earnings: SliceStats };
      origins: OriginRow[];
    }
  >;
}

export interface ExperimentListItem {
  ticker: string;
  name: string;
  period: ExperimentResults["period"];
  events: ExperimentResults["events"];
  horizons: number[];
  skill: Partial<Record<ModelKey, number>>;
}
