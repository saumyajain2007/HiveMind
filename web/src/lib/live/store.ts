import { useStore } from "zustand";
import { createStore } from "zustand/vanilla";

import { SeriesBuffer } from "./buffer";
import { LiveSocket, streamUrl } from "./socket";
import type {
  FeedItem,
  HelloMessage,
  LiveStatus,
  ProgressMessage,
  StreamMessage,
  TickMessage,
} from "./types";

/** Ticks kept per series: 250 days × 96 ticks, enough for the longest allowed run. */
export const LIVE_CAPACITY = 24_000;
const FEED_LIMIT = 200;

/**
 * Per-tick series live in ring buffers outside React state. Frames are appended as they
 * arrive, and the store's `version` is bumped at most once per animation frame, so
 * subscribers re-render at display rate, not message rate.
 */
export const series = {
  tick: new SeriesBuffer(LIVE_CAPACITY),
  price: new SeriesBuffer(LIVE_CAPACITY),
  vTrue: new SeriesBuffer(LIVE_CAPACITY),
  volume: new SeriesBuffer(LIVE_CAPACITY),
  confidence: new SeriesBuffer(LIVE_CAPACITY),
  iv: new SeriesBuffer(LIVE_CAPACITY),
  atmCall: new SeriesBuffer(LIVE_CAPACITY),
  mmInventory: new SeriesBuffer(LIVE_CAPACITY),
  imbalance: new SeriesBuffer(LIVE_CAPACITY),
};

/** What the feed and charts need to know about each item (event or narrative). */
export interface ItemMeta {
  item: number;
  tick: number;
  kind: string;
  origin: "event" | "mutation" | "invention" | "price_news";
  label: string;
  parent: number;
  sentiment: number;
  credibility: number;
  seeding?: string;
}

/** Everything born during the run, in order (event markers, feed history); never trimmed. */
export const born: ItemMeta[] = [];
/** Awareness history per item id: parallel tick / count arrays. */
export const awarenessHistory = new Map<number, { ticks: number[]; counts: number[] }>();

function remember(msg: Extract<StreamMessage, { type: "event" | "narrative" }>): void {
  const isEvent = msg.type === "event";
  born.push({
    item: isEvent ? (msg.item ?? msg.id) : msg.id,
    tick: msg.tick,
    kind: isEvent ? msg.kind : msg.origin === "price_news" ? "price_move" : msg.origin,
    origin: isEvent ? (msg.kind === "price_move" ? "price_news" : "event") : msg.origin,
    label: msg.label ?? (isEvent ? msg.kind : msg.origin),
    parent: msg.parent ?? -1,
    sentiment: msg.sentiment,
    credibility: msg.credibility,
    seeding: isEvent ? msg.seeding : undefined,
  });
}

/** Frames per second over the last second of wall-clock time. */
const frameTimes: number[] = [];
export function framesPerSecond(now = performance.now()): number {
  while (frameTimes.length && now - frameTimes[0]! > 1000) frameTimes.shift();
  return frameTimes.length;
}

export interface LiveState {
  runId: string | null;
  status: LiveStatus;
  error: string | null;
  meta: HelloMessage | null;
  last: TickMessage | null;
  feed: FeedItem[];
  summary: Record<string, unknown> | null;
  progress: ProgressMessage | null;
  version: number;
  framesReceived: number;
}

const initial: LiveState = {
  runId: null,
  status: "idle",
  error: null,
  meta: null,
  last: null,
  feed: [],
  summary: null,
  progress: null,
  version: 0,
  framesReceived: 0,
};

export const liveStore = createStore<LiveState>()(() => ({ ...initial }));

// ----------------------------------------------------------------------------- batching

let pendingLast: TickMessage | null = null;
let pendingFeed: FeedItem[] = [];
let pendingFrames = 0;
let flushScheduled = false;

const schedule: (cb: () => void) => void =
  typeof requestAnimationFrame === "function"
    ? (cb) => void requestAnimationFrame(cb)
    : (cb) => void setTimeout(cb, 16);

export function flushNow(): void {
  flushScheduled = false;
  if (!pendingLast && pendingFeed.length === 0 && pendingFrames === 0) return;
  const s = liveStore.getState();
  liveStore.setState({
    last: pendingLast ?? s.last,
    feed: pendingFeed.length ? [...pendingFeed.reverse(), ...s.feed].slice(0, FEED_LIMIT) : s.feed,
    version: s.version + 1,
    framesReceived: s.framesReceived + pendingFrames,
  });
  pendingLast = null;
  pendingFeed = [];
  pendingFrames = 0;
}

function scheduleFlush() {
  if (flushScheduled) return;
  flushScheduled = true;
  schedule(flushNow);
}

/** Apply one stream message. Exported for tests and for the mock replay. */
export function ingest(msg: StreamMessage): void {
  switch (msg.type) {
    case "hello":
      liveStore.setState({ meta: msg });
      return;
    case "tick":
      series.tick.push(msg.tick);
      series.price.push(msg.price);
      series.vTrue.push(msg.v_true);
      series.volume.push(msg.volume);
      series.confidence.push(msg.confidence);
      series.iv.push(msg.iv);
      series.atmCall.push(msg.atm_call);
      series.mmInventory.push(msg.mm_inventory ?? 0);
      series.imbalance.push(msg.imbalance ?? 0);
      if (msg.awareness)
        for (const [k, n] of Object.entries(msg.awareness)) {
          const id = Number(k);
          let h = awarenessHistory.get(id);
          if (!h) awarenessHistory.set(id, (h = { ticks: [], counts: [] }));
          h.ticks.push(msg.tick);
          h.counts.push(n);
        }
      frameTimes.push(typeof performance !== "undefined" ? performance.now() : Date.now());
      if (frameTimes.length > 4000) frameTimes.splice(0, 2000);
      pendingLast = msg;
      pendingFrames += 1;
      scheduleFlush();
      return;
    case "event":
    case "narrative":
      remember(msg);
      pendingFeed.push({ ...msg, receivedAt: Date.now() });
      pendingFrames += 1;
      scheduleFlush();
      return;
    case "progress":
      liveStore.setState({ progress: msg });
      return;
    case "done":
      flushNow();
      liveStore.setState({ summary: msg.summary });
      return;
    case "error":
      flushNow();
      liveStore.setState({ error: msg.message });
      return;
  }
}

// ----------------------------------------------------------------------------- session

let socket: LiveSocket | null = null;

export function resetLive(): void {
  socket?.close();
  socket = null;
  for (const b of Object.values(series)) b.clear();
  born.length = 0;
  awarenessHistory.clear();
  frameTimes.length = 0;
  pendingLast = null;
  pendingFeed = [];
  pendingFrames = 0;
  liveStore.setState({ ...initial });
}

/** Subscribe to a run's live stream (replaces any current one). */
export function connectRun(
  runId: string,
  opts: { WebSocketImpl?: typeof WebSocket; url?: string } = {},
): void {
  resetLive();
  liveStore.setState({ runId, status: "connecting" });
  socket = new LiveSocket({
    url: opts.url ?? streamUrl(runId),
    WebSocketImpl: opts.WebSocketImpl,
    onMessage: ingest,
    lastTick: () => (series.tick.length ? series.tick.last() : null),
    onStatus: (status, detail) =>
      liveStore.setState(detail ? { status, error: detail } : { status }),
  });
  socket.connect();
}

export function disconnectRun(): void {
  socket?.close();
  socket = null;
  const s = liveStore.getState();
  if (s.status !== "done") liveStore.setState({ status: s.runId ? "done" : "idle" });
}

// ----------------------------------------------------------------------------- hooks

export function useLive<T>(selector: (s: LiveState) => T): T {
  return useStore(liveStore, selector);
}

/** Re-renders when new frames have been flushed; read `series` inside. */
export function useLiveVersion(): number {
  return useStore(liveStore, (s) => s.version);
}
