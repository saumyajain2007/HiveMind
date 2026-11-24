/**
 * Messages on `WS /api/v1/runs/{id}/stream` (issues.md #17).
 *
 * The API (`api/marketsim_api/routes/stream.py`) sends exactly these shapes; the mock server
 * (src/mocks) replays a recorded run with them.
 */

export interface HelloMessage {
  type: "hello";
  run_id: string;
  n_agents: number;
  days: number;
  seed: number;
  ticks_per_day: number;
  initial_price: number;
  mode?: "single" | "montecarlo";
  runs?: number;
  n_nodes?: number;
  /** Node ids whose awareness is streamed in `tick.node_seen` (network view). */
  node_sample?: number[];
  /** True when a finished run is replayed from disk. */
  replay?: boolean;
}

export interface TickMessage {
  type: "tick";
  tick: number;
  price: number;
  v_true: number;
  volume: number;
  confidence: number; // mean investor confidence, -1..1
  iv: number; // annualised implied vol
  atm_call: number;
  awareness?: Record<string, number>; // item id -> agents aware
  mm_inventory?: number; // market-maker inventory (shares)
  imbalance?: number; // retail order imbalance, -1..1
  /** [index into hello.node_sample, item id] pairs that became aware this tick. */
  node_seen?: [number, number][];
}

export interface EventMessage {
  type: "event";
  tick: number;
  id: number;
  kind: string;
  seeding: string;
  sentiment: number;
  credibility: number;
  label?: string;
  item?: number; // id of the item the event created (awareness is keyed by item id)
  parent?: number; // parent item id, or -1
  salience?: number;
  true_impact?: number;
}

export interface NarrativeMessage {
  type: "narrative";
  tick: number;
  id: number;
  parent: number;
  origin: "event" | "mutation" | "invention" | "price_news";
  sentiment: number;
  credibility: number;
  label?: string;
}

export interface DoneMessage {
  type: "done";
  status?: "done" | "cancelled";
  summary: Record<string, unknown>;
}

/** Monte Carlo progress: runs finished so far and the quantile bands of those runs. */
export interface ProgressMessage {
  type: "progress";
  done: number;
  total: number;
  quantiles: Record<string, number[]>;
}

export interface ErrorMessage {
  type: "error";
  message: string;
}

export type StreamMessage =
  | HelloMessage
  | TickMessage
  | EventMessage
  | NarrativeMessage
  | ProgressMessage
  | DoneMessage
  | ErrorMessage;

/** Anything that appears in the news feed. */
export type FeedItem = (EventMessage | NarrativeMessage) & { receivedAt: number };

export type LiveStatus = "idle" | "connecting" | "live" | "reconnecting" | "done" | "error";
