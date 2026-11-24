/**
 * Synthetic shocks, mirroring `marketsim.events.hawkes_events`: discrete-time self-exciting
 * arrivals N_t ~ Poisson(mu + alpha · Σ e^{-beta k} N_{t-k}) with randomised attributes.
 */
import type { Schemas } from "@/lib/api/client";

type EventSpec = Schemas["EventSpec"];

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

function poisson(lam: number, rand: () => number): number {
  const l = Math.exp(-lam);
  let k = 0;
  let p = 1;
  do {
    k++;
    p *= rand();
  } while (p > l && k < 50);
  return k - 1;
}

function normal(rand: () => number): number {
  return Math.sqrt(-2 * Math.log(Math.max(rand(), 1e-12))) * Math.cos(2 * Math.PI * rand());
}

const KINDS: [EventSpec["kind"], number, EventSpec["seeding"][], [number, number], boolean][] = [
  ["rumour", 0.35, ["anonymous", "influencer"], [0.1, 0.4], false],
  ["leak", 0.1, ["insider"], [0.4, 0.7], true],
  ["macro", 0.15, ["outlet"], [0.7, 0.95], true],
  ["product", 0.15, ["official", "outlet"], [0.7, 0.95], true],
  ["regulatory", 0.1, ["official", "outlet"], [0.75, 0.95], true],
  ["earnings", 0.1, ["official"], [0.85, 1], true],
  ["statement", 0.05, ["official"], [0.8, 1], false],
];

export interface HawkesParams {
  mu: number;
  alpha: number;
  beta: number;
  seed: number;
  impactSd: number;
}

export const DEFAULT_HAWKES: HawkesParams = {
  mu: 0.01,
  alpha: 0.4,
  beta: 0.5,
  seed: 1,
  impactSd: 0.02,
};

/** Branching ratio α·e^{-β}/(1 − e^{-β}); the process is stationary below 1. */
export function branchingRatio(p: HawkesParams): number {
  const d = Math.exp(-p.beta);
  return (p.alpha * d) / (1 - d);
}

export function hawkesEvents(p: HawkesParams, nTicks: number, startId: number): EventSpec[] {
  const rand = mulberry32(p.seed);
  const total = KINDS.reduce((a, k) => a + k[1], 0);
  const out: EventSpec[] = [];
  let excite = 0;
  const decay = Math.exp(-p.beta);
  let id = startId;
  for (let t = 0; t < nTicks; t++) {
    const n = poisson(p.mu + p.alpha * excite, rand);
    for (let j = 0; j < n; j++) {
      let r = rand() * total;
      const spec = KINDS.find((k) => (r -= k[1]) < 0) ?? KINDS[0]!;
      const [kind, , seedings, [cLo, cHi], real] = spec;
      const impact = real ? Math.max(-0.3, Math.min(0.3, normal(rand) * p.impactSd)) : 0;
      const lean = real ? Math.tanh(impact / Math.max(p.impactSd, 1e-9)) : rand() * 2 - 1;
      const sentiment = Math.max(-1, Math.min(1, 0.7 * lean + 0.25 * normal(rand)));
      const r2 = (x: number) => Math.round(x * 100) / 100;
      out.push({
        id: id++,
        tick: t,
        kind,
        ticker: 0,
        true_impact: Math.round(impact * 1000) / 1000,
        sentiment: r2(sentiment),
        credibility: r2(cLo + rand() * (cHi - cLo)),
        salience: r2(0.2 + rand() * 0.6),
        complexity: r2(0.2 + rand() * 0.6),
        seeding: seedings[Math.floor(rand() * seedings.length)]!,
        parent: -1,
        topic: "finance",
        label: `Shock: ${kind}${real ? ` (${impact >= 0 ? "+" : ""}${(impact * 100).toFixed(1)}%)` : ""}`,
      });
    }
    excite = (excite + n) * decay;
  }
  return out;
}
