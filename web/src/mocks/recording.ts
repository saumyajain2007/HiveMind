/**
 * A deterministic, synthetic "recorded run" of the demo scenario, in the exact stream format
 * of `WS /api/v1/runs/{id}/stream`. Used by the mock server until the real stream (#17)
 * exists. These numbers are generated here, not by the engine.
 */
import type { StreamMessage } from "@/lib/live/types";

const TICKS_PER_DAY = 96;
const OPEN = 38;
const CLOSE = 64;

function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function gaussian(rand: () => number) {
  const u = Math.max(rand(), 1e-12);
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * rand());
}

const logistic = (x: number) => 1 / (1 + Math.exp(-x));

interface ItemSpec {
  id: number;
  born: number;
  reach: number; // final share of agents aware
  speed: number; // ticks per e-fold
}

export interface Recording {
  hello: Omit<Extract<StreamMessage, { type: "hello" }>, "run_id">;
  messages: StreamMessage[]; // ticks interleaved with events/narratives, in order
  summary: Record<string, unknown>;
}

export function makeRecording(
  opts: { days?: number; nAgents?: number; seed?: number } = {},
): Recording {
  const days = opts.days ?? 5;
  const n = opts.nAgents ?? 10_000;
  const rand = mulberry32(opts.seed ?? 7);
  const T = days * TICKS_PER_DAY;

  const rumour = TICKS_PER_DAY + 44;
  const mutation = rumour + 14;
  const denial = 2 * TICKS_PER_DAY + 40;
  const earnings = 3 * TICKS_PER_DAY + 39;
  const invention = earnings + 5;

  const discrete: StreamMessage[][] = Array.from({ length: T }, () => []);
  const at = (t: number, m: StreamMessage) => t < T && discrete[t]!.push(m);
  at(rumour, {
    type: "event",
    tick: rumour,
    id: 0,
    kind: "rumour",
    seeding: "anonymous",
    sentiment: 0.8,
    credibility: 0.2,
    label: "Forum post: Acme in takeover talks",
  });
  at(mutation, {
    type: "narrative",
    tick: mutation,
    id: 100,
    parent: 0,
    origin: "mutation",
    sentiment: 1.0,
    credibility: 0.14,
    label: "“Deal at a 40% premium, signed Friday”",
  });
  at(denial, {
    type: "event",
    tick: denial,
    id: 1,
    kind: "statement",
    seeding: "official",
    sentiment: -0.3,
    credibility: 0.9,
    label: "Acme denies takeover reports",
  });
  at(earnings, {
    type: "event",
    tick: earnings,
    id: 2,
    kind: "earnings",
    seeding: "official",
    sentiment: -0.7,
    credibility: 0.95,
    label: "Q3 revenue misses estimates",
  });
  at(invention, {
    type: "narrative",
    tick: invention,
    id: 101,
    parent: -1,
    origin: "invention",
    sentiment: -0.8,
    credibility: 0.3,
    label: "“The CFO is about to resign”",
  });

  const items: ItemSpec[] = [
    { id: 0, born: rumour, reach: 0.41, speed: 7 },
    { id: 100, born: mutation, reach: 0.22, speed: 9 },
    { id: 1, born: denial, reach: 0.28, speed: 5 },
    { id: 2, born: earnings, reach: 0.36, speed: 3 },
    { id: 101, born: invention, reach: 0.12, speed: 6 },
  ];

  const sigmaTick = 0.3 / Math.sqrt(252) / Math.sqrt(CLOSE - OPEN);
  let logP = Math.log(100);
  let vTrue = 100;
  let conf = 0.02;
  let iv = 0.3;
  let headline = 100; // price at the last price headline
  let priceNewsId = 200;
  const messages: StreamMessage[] = [];
  const closes: number[] = [];

  for (let t = 0; t < T; t++) {
    const inDay = t % TICKS_PER_DAY;
    const open = inDay >= OPEN && inDay < CLOSE;

    // belief drift from the narrative story
    let target = 0;
    if (t >= rumour) target += 0.45 * Math.exp(-(t - rumour) / 60);
    if (t >= denial) target -= 0.3 * Math.exp(-(t - denial) / 50);
    if (t >= earnings) target -= 0.4 * Math.exp(-(t - earnings) / 80);
    conf += 0.06 * (target - conf) + 0.012 * gaussian(rand);
    conf = Math.max(-1, Math.min(1, conf));

    if (t === earnings) vTrue *= Math.exp(-0.05);
    if (t >= earnings) iv = 0.3 + 0.08 * Math.exp(-(t - earnings) / 120);

    let volume = 0;
    if (open) {
      let r = sigmaTick * gaussian(rand) + 0.0016 * conf;
      if (t === earnings) r -= 0.045;
      if (t >= denial && t < denial + 3) r -= 0.006;
      logP += r;
      const eventBoost = [rumour, denial, earnings].some((e) => t >= e && t < e + 6) ? 3.2 : 1;
      volume = Math.round((900 + (1400 * Math.abs(r)) / sigmaTick + 300 * rand()) * eventBoost);
    }
    const price = Math.exp(logP);
    if (inDay === CLOSE - 1) closes.push(price);

    if (open && Math.abs(price / headline - 1) > 0.04) {
      const up = price > headline;
      at(t, {
        type: "narrative",
        tick: t,
        id: priceNewsId++,
        parent: -1,
        origin: "price_news",
        sentiment: up ? 0.6 : -0.6,
        credibility: 0.85,
        label: `Acme ${up ? "up" : "down"} ${Math.abs((price / headline - 1) * 100).toFixed(1)}%`,
      });
      headline = price;
    }

    const awareness: Record<string, number> = {};
    for (const it of items) {
      if (t >= it.born) {
        awareness[String(it.id)] = Math.round(
          n * it.reach * logistic((t - it.born - 4 * it.speed) / it.speed),
        );
      }
    }

    messages.push(...discrete[t]!);
    messages.push({
      type: "tick",
      tick: t,
      price,
      v_true: vTrue,
      volume,
      confidence: conf,
      iv,
      atm_call: 0.4 * price * iv * Math.sqrt(30 / 365),
      awareness,
    });
  }

  const finalPrice = Math.exp(logP);
  const summary = {
    final_price: finalPrice,
    return: finalPrice / 100 - 1,
    min_price: Math.min(
      ...messages.filter((m) => m.type === "tick").map((m) => (m as { price: number }).price),
    ),
    daily_closes: closes,
    items_created: items.length + (priceNewsId - 200),
  };
  return {
    hello: {
      type: "hello",
      n_agents: n,
      days,
      seed: opts.seed ?? 7,
      ticks_per_day: TICKS_PER_DAY,
      initial_price: 100,
    },
    messages,
    summary,
  };
}
