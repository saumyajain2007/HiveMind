/**
 * Messages on `WS /api/v1/runs/{id}/stream` (issues.md #17).
 *
 * The API side of this stream is built in issue #17 and must send exactly these shapes.
 * Until then the mock server (src/mocks) replays a recorded run with them.
 */

export interface HelloMessage {
  type: "hello";
  run_id: string;
  n_agents: number;
  days: number;
  seed: number;
  ticks_per_day: number;
  initial_price: number;
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
  summary: Record<string, unknown>;
}

export interface ErrorMessage {
  type: "error";
  message: string;
}

export type StreamMessage =
  HelloMessage | TickMessage | EventMessage | NarrativeMessage | DoneMessage | ErrorMessage;

/** Anything that appears in the news feed. */
export type FeedItem = (EventMessage | NarrativeMessage) & { receivedAt: number };

export type LiveStatus = "idle" | "connecting" | "live" | "reconnecting" | "done" | "error";
