import type { LiveStatus, StreamMessage } from "./types";

export interface LiveSocketOptions {
  url: string;
  onMessage: (msg: StreamMessage) => void;
  onStatus?: (status: LiveStatus, detail?: string) => void;
  /** Last tick received; sent as `?after=` on reconnect so the server resumes there. */
  lastTick?: () => number | null;
  baseDelayMs?: number;
  maxDelayMs?: number;
  maxRetries?: number;
  /** Injectable for tests. */
  WebSocketImpl?: typeof WebSocket;
  random?: () => number;
}

/**
 * A typed WebSocket client with exponential back-off and jitter.
 *
 * It reconnects after unexpected closes until `maxRetries` attempts fail in a row. It stops
 * for good after a `done` or `error` message, or when `close()` is called.
 */
export class LiveSocket {
  private ws: WebSocket | null = null;
  private attempts = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private finished = false;
  private readonly opts: Required<Omit<LiveSocketOptions, "onStatus" | "lastTick">> &
    Pick<LiveSocketOptions, "onStatus" | "lastTick">;

  constructor(options: LiveSocketOptions) {
    // `??` rather than spreading defaults first: an explicit `undefined` must not erase a default.
    this.opts = {
      ...options,
      baseDelayMs: options.baseDelayMs ?? 500,
      maxDelayMs: options.maxDelayMs ?? 8_000,
      maxRetries: options.maxRetries ?? 8,
      WebSocketImpl: options.WebSocketImpl ?? globalThis.WebSocket,
      random: options.random ?? Math.random,
    };
  }

  connect(): void {
    this.finished = false;
    this.open(false);
  }

  close(): void {
    this.finished = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    const ws = this.ws;
    this.ws = null;
    ws?.close(1000, "client closed");
  }

  /** Delay before reconnect attempt `n` (1-based): base · 2^(n−1), capped, with ±20% jitter. */
  delayFor(n: number): number {
    const raw = Math.min(this.opts.maxDelayMs, this.opts.baseDelayMs * 2 ** (n - 1));
    return Math.round(raw * (0.8 + 0.4 * this.opts.random()));
  }

  private url(): string {
    const after = this.opts.lastTick?.();
    if (after == null) return this.opts.url;
    const sep = this.opts.url.includes("?") ? "&" : "?";
    return `${this.opts.url}${sep}after=${after}`;
  }

  private open(isRetry: boolean): void {
    this.opts.onStatus?.(isRetry ? "reconnecting" : "connecting");
    const ws = new this.opts.WebSocketImpl(this.url());
    this.ws = ws;
    ws.onopen = () => {
      this.attempts = 0;
      this.opts.onStatus?.("live");
    };
    ws.onmessage = (ev: MessageEvent) => {
      let msg: StreamMessage;
      try {
        msg = JSON.parse(String(ev.data)) as StreamMessage;
      } catch {
        return; // ignore malformed frames
      }
      if (msg.type === "done" || msg.type === "error") this.finished = true;
      this.opts.onMessage(msg);
      if (msg.type === "done") this.opts.onStatus?.("done");
      if (msg.type === "error") this.opts.onStatus?.("error", msg.message);
    };
    ws.onclose = () => {
      if (this.ws !== ws) return; // superseded or closed by us
      this.ws = null;
      if (this.finished) return;
      this.attempts += 1;
      if (this.attempts > this.opts.maxRetries) {
        this.finished = true;
        this.opts.onStatus?.("error", "connection lost");
        return;
      }
      this.opts.onStatus?.("reconnecting");
      this.timer = setTimeout(() => this.open(true), this.delayFor(this.attempts));
    };
  }
}

export function streamUrl(
  runId: string,
  loc: Pick<Location, "protocol" | "host"> = window.location,
): string {
  const proto = loc.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${loc.host}/api/v1/runs/${encodeURIComponent(runId)}/stream`;
}
