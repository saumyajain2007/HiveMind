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

// ----------------------------------------------------------------------------- strategy.json

export interface DistStats {
  mean: number;
  sd: number;
  expected_return: number;
  p_up: number;
  log_mu: number;
  log_sd: number;
  q05: number;
  q25: number;
  q50: number;
  q75: number;
  q95: number;
}

export type ForecastRow = DistStats & {
  origin: string;
  target: string;
  close: number;
  actual: number;
  actual_return: number;
  z: number;
  rw_sd_log: number;
  rw_z: number;
  raw_mean: number;
  raw_sd: number;
  raw_min: number;
  raw_max: number;
};

export interface ForecastSummary {
  n: number;
  mean_actual_return: number;
  mean_expected_return: number;
  bias: number;
  rmse_model: number;
  rmse_random_walk: number;
  mae_model: number;
  mae_random_walk: number;
  information_coefficient: number;
  ic_t: number;
  sign_hit_rate: number;
  z_mean: number;
  z_sd: number;
  rw_z_mean: number;
  rw_z_sd: number;
  coverage_50: number;
  coverage_90: number;
  rw_coverage_50: number;
  rw_coverage_90: number;
  mean_forecast_sd: number;
  mean_rw_sd: number;
  realised_rms: number;
  vol_skill_model: number;
  vol_skill_random_walk: number;
}

export interface StrategyResult {
  label: string;
  description: string;
  total_return: number;
  cagr: number;
  ann_vol: number;
  sharpe: number;
  sharpe_ci95: [number, number];
  p_sharpe_not_above_buy_hold: number;
  sortino: number;
  max_drawdown: number;
  calmar: number;
  hit_rate: number;
  exposure: number;
  turnover_per_year: number;
  costs: number;
  alpha_ann: number;
  alpha_t: number;
  beta: number;
  mean_daily: number;
  t_mean: number;
  equity: number[];
  drawdown?: number[];
  probabilistic_sharpe?: number;
  deflated_sharpe?: number;
  trials?: number;
  n_trades?: number;
  win_rate?: number;
  profit_factor?: number | null;
  expectancy?: number;
  max_drawdown_days?: number;
  information_ratio?: number | null;
  trades?: {
    side: string;
    entry: string;
    exit: string;
    bars: number;
    weight: number;
    ret: number;
  }[];
}

export interface Fitness {
  n: number;
  information_coefficient: number;
  ic_t: number;
  rank_ic: number;
  hit_rate: number;
  brier: number;
  brier_climatology: number;
  log_loss: number;
  log_loss_climatology: number;
  calibration: { p_mean: number; freq_up: number; n: number }[];
}

export type LatestHorizon = DistStats & {
  target: string;
  runs: number[];
  random_walk_sd: number;
  scheduled_earnings: number;
};

export interface StrategyDoc {
  ticker: string;
  name: string;
  period: { train: [string, string]; test: [string, string] };
  agent_params: Record<string, number>;
  latest: { date: string; close: number; horizons: Record<string, LatestHorizon> };
  forecasts: Record<string, { summary: ForecastSummary; rows: ForecastRow[] }>;
  fitness?: Record<string, { train: Fitness; test: Fitness }>;
  strategy: {
    cost_bps: number;
    trials?: number;
    max_leverage: number;
    vol_target_daily: number;
    dates: string[];
    start: string;
    results: Record<string, StrategyResult>;
  };
}

// ----------------------------------------------------------------------------- isolation

export interface EffectStats {
  path: { mean: number[]; lo: number[]; hi: number[]; se: number[] };
  final: { mean: number; se: number; ci95: [number, number]; t: number; p_positive: number };
  one_day: { mean: number; se: number };
  peak: { value: number; tick: number };
  ticks_to_half_peak: number | null;
  window_effect?: number;
}

export type EventEffect = EffectStats & {
  id: number;
  label: string;
  kind: string;
  tick: number;
  day: number;
  true_impact: number;
  sentiment: number;
  credibility: number;
  salience: number;
  seeding: string;
  pass_through: number | null;
  extra_volume: number;
  share_of_total: number | null;
};

export interface IsolationResult {
  seeds: number;
  cancelled: boolean;
  n_ticks: number;
  every: number;
  tick: number[];
  baseline: { mean: number[]; with_events: number[] };
  total: EffectStats;
  events: EventEffect[];
  isolated_sum: number;
  interaction: number;
}

export type RealWindow = IsolationResult & {
  origin: string;
  target: string;
  start: string;
  origin_tick: number;
  real_move: number;
  real_abnormal_move: number;
  market_move: number;
  measured_reactions: {
    date: string;
    form: string;
    items: string[];
    group: string;
    label: number | null;
  }[];
};

export interface RealIsolation {
  ticker: string;
  name: string;
  horizon: number;
  runs: number;
  windows: RealWindow[];
}

// ----------------------------------------------------------------------------- event library

export interface CatalogRow {
  group: string;
  n: number;
  tickers: number;
  mean_ar: number;
  median_ar: number;
  t_direction: number;
  share_up: number;
  mean_abs_ar: number;
  normal_abs_ar: number;
  excess_abs_ar: number;
  abs_sar: number;
  share_big: number;
  car_mean: number[];
  car_abs_mean: number[];
  day0_share_of_5d: number;
  volume_ratio_median: number;
}

export interface EventLibrary {
  tickers: string[];
  n_events: number;
  split: string;
  catalog: CatalogRow[];
  earnings_by_ticker: {
    ticker: string;
    name: string;
    n: number;
    mean_abs_ar: number;
    abs_sar: number;
    share_up: number;
    largest: number;
  }[];
  model: {
    n_train: number;
    n_test: number;
    pooled: ImpactMetrics;
    own_vs_pooled?: {
      n: number;
      size_mae_own: number;
      size_mae_pooled: number;
      size_corr_own: number;
      size_corr_pooled: number;
    };
  };
  biggest: {
    ticker: string;
    name: string;
    date: string;
    form: string;
    items: string[];
    group: string;
    ar: number;
    sar: number;
    volume_ratio: number;
  }[];
}

// ----------------------------------------------------------------------------- algo run

export interface AlgoRun {
  ticker: string;
  period: [string, string];
  dates: string[];
  close: number[];
  positions: number[];
  equity: number[];
  drawdown: number[];
  buy_hold_equity: number[];
  trades: {
    side: string;
    entry: string;
    exit: string;
    bars: number;
    weight: number;
    ret: number;
  }[];
  stats: Record<string, number | null>;
  sharpe_ci95: [number, number];
  fitness: {
    n: number;
    information_coefficient: number;
    ic_t: number;
    rank_ic: number;
    hit_rate: number;
    brier: number;
    brier_climatology: number;
  };
  features: string[];
  rule: string;
}

// ----------------------------------------------------------------------------- stock import

export interface StockListing {
  ticker: string;
  name: string;
  last_date: string;
  last_close: number;
}

export interface StockHeadline {
  date: string;
  released: string;
  reaction_date: string;
  index: number;
  source: string;
  form: string;
  group: string;
  headline: string;
  abnormal_return: number | null;
  url: string | null;
}

export interface SocialPost {
  date: string;
  platform: string;
  handle: string;
  text: string;
  likes: number;
  sentiment: number;
}

export interface ClassifiedEvent {
  date: string;
  form: string;
  group: string;
  proba: [number, number, number];
  predicted: string;
  actual: string;
  expected_ar: number;
  predicted_size: number;
  actual_ar: number;
}

export interface StockImport {
  ticker: string;
  name: string;
  period: [string, string];
  dates: string[];
  close: number[];
  volume: number[];
  sources: { name: string; provider: string; count: number }[];
  headlines: StockHeadline[];
  social: {
    platforms: string[];
    mentions: number[];
    by_platform: Record<string, number[]>;
    sentiment: number[];
    posts: SocialPost[];
    n_posts: number;
  };
  classification: {
    split: string;
    classes: string[];
    events: ClassifiedEvent[];
    metrics: {
      n?: number;
      accuracy?: number;
      majority_accuracy?: number;
      direction_hit_rate?: number | null;
      size_corr?: number | null;
      size_mae?: number;
      mean_abs_ar?: number;
    };
  };
}
