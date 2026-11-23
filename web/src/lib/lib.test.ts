import { afterEach, describe, expect, it, vi } from "vitest";

import { formatCompact, formatPrice, formatSigned, formatSignedPct, simClock } from "./format";
import { SeriesBuffer } from "./live/buffer";
import { LiveSocket, streamUrl } from "./live/socket";
import { flushNow, ingest, liveStore, resetLive, series } from "./live/store";
import type { LiveStatus, StreamMessage, TickMessage } from "./live/types";

describe("format", () => {
  it("compacts large numbers and keeps small ones exact", () => {
    expect(formatCompact(1284)).toBe("1,284");
    expect(formatCompact(12_900)).toBe("12.9K");
    expect(formatCompact(4_200_000)).toBe("4.2M");
    expect(formatCompact(null)).toBe("—");
  });
  it("signs with a true minus and no negative zero", () => {
    expect(formatSignedPct(0.0124)).toBe("+1.24%");
    expect(formatSignedPct(-0.008)).toBe("−0.80%");
    expect(formatSignedPct(-0.00001)).toBe("0.00%");
    expect(formatSigned(-0.18)).toBe("−0.18");
    expect(formatPrice(101.5)).toBe("101.50");
  });
  it("maps ticks to the simulation clock and market hours", () => {
    expect(simClock(0).label).toBe("Day 1 · 00:00");
    expect(simClock(38)).toMatchObject({ day: 1, hh: 9, mm: 30, open: true });
    expect(simClock(63).open).toBe(true);
    expect(simClock(64)).toMatchObject({ hh: 16, mm: 0, open: false });
    expect(simClock(96 + 41).label).toBe("Day 2 · 10:15");
  });
});

describe("SeriesBuffer", () => {
  it("keeps the newest values once full, oldest first", () => {
    const b = new SeriesBuffer(3);
    [1, 2, 3, 4, 5].forEach((v) => b.push(v));
    expect(b.length).toBe(3);
    expect(b.toArray()).toEqual([3, 4, 5]);
    expect(b.first()).toBe(3);
    expect(b.last()).toBe(5);
    expect(b.toArray(2)).toEqual([4, 5]);
    expect(Number.isNaN(b.at(3))).toBe(true);
    b.clear();
    expect(b.length).toBe(0);
  });
});

const tick = (t: number, price = 100): TickMessage => ({
  type: "tick",
  tick: t,
  price,
  v_true: 100,
  volume: 10,
  confidence: 0.1,
  iv: 0.3,
  atm_call: 3,
});

describe("live store", () => {
  afterEach(() => resetLive());

  it("buffers frames and bumps the version once per flush", () => {
    const v0 = liveStore.getState().version;
    for (let t = 0; t < 50; t++) ingest(tick(t, 100 + t));
    expect(liveStore.getState().version).toBe(v0); // nothing re-renders until the flush
    expect(series.price.length).toBe(50);
    flushNow();
    const s = liveStore.getState();
    expect(s.version).toBe(v0 + 1);
    expect(s.last?.price).toBe(149);
    expect(s.framesReceived).toBe(50);
  });

  it("collects events newest first and stores the summary", () => {
    ingest({
      type: "event",
      tick: 5,
      id: 0,
      kind: "rumour",
      seeding: "anonymous",
      sentiment: 0.8,
      credibility: 0.2,
    });
    ingest({
      type: "narrative",
      tick: 9,
      id: 100,
      parent: 0,
      origin: "mutation",
      sentiment: 1,
      credibility: 0.1,
    });
    ingest({ type: "done", summary: { final_price: 99 } });
    const s = liveStore.getState();
    expect(s.feed.map((f) => f.id)).toEqual([100, 0]);
    expect(s.summary).toEqual({ final_price: 99 });
  });
});

// --------------------------------------------------------------------------- socket

class FakeWS {
  static instances: FakeWS[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;
  constructor(readonly url: string) {
    FakeWS.instances.push(this);
  }
  open() {
    this.onopen?.();
  }
  send(msg: StreamMessage) {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
  drop() {
    this.onclose?.();
  }
  close() {
    this.closed = true;
    this.onclose?.();
  }
}

describe("LiveSocket", () => {
  afterEach(() => {
    FakeWS.instances = [];
    vi.useRealTimers();
  });

  function make(extra: Partial<ConstructorParameters<typeof LiveSocket>[0]> = {}) {
    const msgs: StreamMessage[] = [];
    const statuses: LiveStatus[] = [];
    let last: number | null = null;
    const sock = new LiveSocket({
      url: "ws://x/api/v1/runs/r1/stream",
      onMessage: (m) => {
        msgs.push(m);
        if (m.type === "tick") last = m.tick;
      },
      onStatus: (s) => statuses.push(s),
      lastTick: () => last,
      WebSocketImpl: FakeWS as unknown as typeof WebSocket,
      random: () => 0.5,
      ...extra,
    });
    return { sock, msgs, statuses };
  }

  it("reconnects with back-off and resumes after the last tick", () => {
    vi.useFakeTimers();
    const { sock, msgs, statuses } = make();
    sock.connect();
    FakeWS.instances[0]!.open();
    FakeWS.instances[0]!.send(tick(41));
    FakeWS.instances[0]!.drop();
    expect(statuses).toEqual(["connecting", "live", "reconnecting"]);
    vi.advanceTimersByTime(499);
    expect(FakeWS.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeWS.instances).toHaveLength(2);
    expect(FakeWS.instances[1]!.url).toBe("ws://x/api/v1/runs/r1/stream?after=41");
    expect(msgs).toHaveLength(1);
  });

  it("uses exponential delays with a cap", () => {
    const { sock } = make({ baseDelayMs: 500, maxDelayMs: 8000 });
    expect([1, 2, 3, 4, 5, 6].map((n) => sock.delayFor(n))).toEqual([
      500, 1000, 2000, 4000, 8000, 8000,
    ]);
  });

  it("stops after done and gives up after max retries", () => {
    vi.useFakeTimers();
    const a = make();
    a.sock.connect();
    FakeWS.instances[0]!.open();
    FakeWS.instances[0]!.send({ type: "done", summary: {} });
    FakeWS.instances[0]!.drop();
    vi.advanceTimersByTime(60_000);
    expect(FakeWS.instances).toHaveLength(1);
    expect(a.statuses.at(-1)).toBe("done");

    FakeWS.instances = [];
    const b = make({ maxRetries: 2 });
    b.sock.connect();
    for (let i = 0; i < 3; i++) {
      FakeWS.instances.at(-1)!.drop();
      vi.advanceTimersByTime(60_000);
    }
    expect(FakeWS.instances).toHaveLength(3);
    expect(b.statuses.at(-1)).toBe("error");
  });

  it("does not reconnect after close()", () => {
    vi.useFakeTimers();
    const { sock } = make();
    sock.connect();
    sock.close();
    vi.advanceTimersByTime(60_000);
    expect(FakeWS.instances).toHaveLength(1);
    expect(FakeWS.instances[0]!.closed).toBe(true);
  });

  it("builds ws/wss URLs from the page location", () => {
    expect(streamUrl("a b", { protocol: "http:", host: "h:1" })).toBe(
      "ws://h:1/api/v1/runs/a%20b/stream",
    );
    expect(streamUrl("x", { protocol: "https:", host: "h" })).toBe("wss://h/api/v1/runs/x/stream");
  });
});
