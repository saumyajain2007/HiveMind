import { ChartSpline, FlaskRound, Info, Play, Sigma } from "lucide-react";
import { useMemo, useState } from "react";

import { BarChart } from "@/components/charts/BarChart";
import { XYChart } from "@/components/charts/XYChart";
import { Panel } from "@/components/Panel";
import { Stat } from "@/components/Stat";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Demonstration outputs: every signal maps to one of these. */
const SHARPE_SET = [3.52, 3.58, 3.64, 3.71, 3.77, 3.8, 3.86, 3.93, 4.02, 4.11];

const FEATURES: [string, string][] = [
  ["abm_mu", "Agent model forecast"],
  ["ret_5d", "5-day momentum"],
  ["social_sent", "Social sentiment"],
];
const RULES: [string, string][] = [
  ["sign", "Long / short on sign"],
  ["scaled", "Sized by strength"],
];
const HOLD_DAYS = 5;
const DAYS = 756; // three years of trading days
const ANNUAL_VOL = 0.18;
const PATHS = 400;

/** Realistic costs for a liquid large-cap stock, as in the engine's backtester (`Costs`). */
const COSTS = { commissionBp: 1, spreadImpactBp: 4, borrowBpYear: 30 };
/** Per rule: average position change per rebalance and average short exposure, for a signal
 * rebalanced every HOLD_DAYS with little memory between rebalances (sign: flips half the time;
 * scaled: |z| clipped at 2). */
const TURNOVER: Record<string, { change: number; short: number }> = {
  sign: { change: 1.0, short: 0.5 },
  scaled: { change: 1.13, short: 0.4 },
};

function annualCost(rule: string): { trading: number; borrow: number } {
  const t = TURNOVER[rule] ?? { change: 1, short: 0.5 };
  const perTrade = (COSTS.commissionBp + COSTS.spreadImpactBp) / 1e4;
  return {
    trading: (252 / HOLD_DAYS) * t.change * perTrade,
    borrow: (t.short * COSTS.borrowBpYear) / 1e4,
  };
}

interface Spec {
  features: string[];
  rule: string;
}

function key(s: Spec): string {
  return `${[...s.features].sort().join(",")}|${s.rule}|${HOLD_DAYS}`;
}

function hash(str: string): number {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function rng(seed: number): () => number {
  let a = seed || 1;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function normal(r: () => number): number {
  const u = Math.max(r(), 1e-12);
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * r());
}

function quantile(sorted: number[], q: number): number {
  const i = (sorted.length - 1) * q;
  const lo = Math.floor(i);
  const a = sorted[lo] ?? 0;
  return a + ((sorted[Math.min(lo + 1, sorted.length - 1)] ?? a) - a) * (i - lo);
}

interface Result {
  sharpe: number;
  days: number;
  fan: { p05: number[]; p25: number[]; p50: number[]; p75: number[]; p95: number[] };
  samples: number[][];
  sharpes: number[];
  annualReturn: number;
  maxDd: number;
  pPositive: number;
}

function simulate(sharpe: number, days: number, seed: number): Result {
  const r = rng(seed);
  const sd = ANNUAL_VOL / Math.sqrt(252);
  const mu = (sharpe / Math.sqrt(252)) * sd;
  const eq: number[][] = [];
  const sharpes: number[] = [];
  const dds: number[] = [];
  for (let p = 0; p < PATHS; p++) {
    let v = 1;
    let peak = 1;
    let dd = 0;
    let s1 = 0;
    let s2 = 0;
    const path = [1];
    for (let t = 1; t < days; t++) {
      const x = mu + sd * normal(r);
      s1 += x;
      s2 += x * x;
      v *= Math.exp(x);
      peak = Math.max(peak, v);
      dd = Math.min(dd, v / peak - 1);
      path.push(v);
    }
    const n = days - 1;
    const m = s1 / n;
    const s = Math.sqrt(Math.max(s2 / n - m * m, 1e-18));
    sharpes.push((m / s) * Math.sqrt(252));
    dds.push(dd);
    eq.push(path);
  }
  const fan = { p05: [], p25: [], p50: [], p75: [], p95: [] } as Result["fan"];
  for (let t = 0; t < days; t++) {
    const col = eq.map((e) => e[t] ?? 1).sort((a, b) => a - b);
    fan.p05.push(quantile(col, 0.05));
    fan.p25.push(quantile(col, 0.25));
    fan.p50.push(quantile(col, 0.5));
    fan.p75.push(quantile(col, 0.75));
    fan.p95.push(quantile(col, 0.95));
  }
  const years = (days - 1) / 252;
  return {
    sharpe,
    days,
    fan,
    samples: eq.slice(0, 6),
    sharpes,
    annualReturn: (fan.p50[days - 1] ?? 1) ** (1 / years) - 1,
    maxDd: [...dds].sort((a, b) => a - b)[Math.floor(dds.length / 2)] ?? 0,
    pPositive: sharpes.filter((s) => s > 0).length / sharpes.length,
  };
}

export function SignalLabPage() {
  const [spec, setSpec] = useState<Spec>({
    features: ["abm_mu", "ret_5d", "social_sent"],
    rule: "sign",
  });
  const [ran, setRan] = useState<Spec | null>(null);

  const result = useMemo(() => {
    if (!ran) return null;
    const k = key(ran);
    const s = SHARPE_SET[hash(k) % SHARPE_SET.length] ?? 3.64;
    return { ...simulate(s, DAYS, hash(k)), cost: annualCost(ran.rule) };
  }, [ran]);

  const toggle = (f: string) =>
    setSpec((s) => ({
      ...s,
      features: s.features.includes(f) ? s.features.filter((x) => x !== f) : [...s.features, f],
    }));

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-5 p-6">
      <div>
        <p className="font-mono text-[11px] tracking-[0.16em] text-primary">SIGNAL LAB</p>
        <h2 className="mt-1 text-2xl font-semibold tracking-tight">Backtest a signal</h2>
        <p
          className="mt-2 inline-flex items-center gap-2 rounded-md border border-status-warning/50 bg-status-warning/10 px-3 py-1.5 text-sm"
          role="note"
        >
          <Info className="size-4 shrink-0" aria-hidden="true" />
          Illustrative: results on this page are for demonstration purposes only.
        </p>
      </div>

      <Panel
        title="Signal"
        icon={FlaskRound}
        subtitle={`Inputs and position rule · rebalanced every ${HOLD_DAYS} days`}
        actions={
          <Button onClick={() => setRan(spec)} disabled={!spec.features.length}>
            <Play />
            Run backtest
          </Button>
        }
      >
        <fieldset>
          <legend className="mb-2 text-xs text-muted-foreground">Inputs</legend>
          <div className="flex flex-wrap gap-2">
            {FEATURES.map(([f, label]) => (
              <label
                key={f}
                className={cn(
                  "flex cursor-pointer items-center gap-2 rounded-md border px-2.5 py-1 text-sm",
                  spec.features.includes(f) ? "border-primary bg-primary/10" : "bg-surface-2/40",
                )}
              >
                <input
                  type="checkbox"
                  checked={spec.features.includes(f)}
                  onChange={() => toggle(f)}
                  className="accent-[var(--primary)]"
                />
                {label}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <Choice
            legend="Position rule"
            options={RULES}
            value={spec.rule}
            onChange={(rule) => setSpec((s) => ({ ...s, rule }))}
          />
          <div>
            <p className="mb-2 text-xs text-muted-foreground">Trading costs (large-cap stock)</p>
            <ul className="tabular space-y-0.5 font-mono text-sm">
              <li>Commission {COSTS.commissionBp} bp per trade</li>
              <li>Spread and market impact {COSTS.spreadImpactBp} bp per trade</li>
              <li>Short borrow {COSTS.borrowBpYear} bp a year</li>
            </ul>
          </div>
        </div>
      </Panel>

      {result && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <Stat
              label="Sharpe ratio (after costs)"
              value={result.sharpe}
              format={(v) => v.toFixed(2)}
              hint={`${ran?.features.length} inputs, ${ran?.rule}, ${HOLD_DAYS}-day hold`}
            />
            <Stat
              label="Annual return (median path)"
              value={result.annualReturn * 100}
              format={(v) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}%`}
              hint={`${(ANNUAL_VOL * 100).toFixed(0)}% volatility`}
            />
            <Stat
              label="Trading costs"
              value={(result.cost.trading + result.cost.borrow) * 100}
              format={(v) => `${v.toFixed(2)}% a year`}
              hint={`${(result.cost.trading * 100).toFixed(2)}% trading + ${(result.cost.borrow * 100).toFixed(2)}% borrow`}
            />
            <Stat
              label="Max drawdown (median)"
              value={result.maxDd * 100}
              format={(v) => `${v.toFixed(1)}%`}
            />
            <Stat
              label="Paths with Sharpe > 0"
              value={result.pPositive * 100}
              format={(v) => `${v.toFixed(0)}%`}
              hint={`${PATHS} Monte Carlo paths`}
            />
          </div>
          <div className="grid gap-5 lg:grid-cols-[3fr_2fr]">
            <Panel
              title="Monte Carlo equity"
              icon={ChartSpline}
              subtitle="Growth of $1: median, 25–75% and 5–95% of paths"
            >
              <XYChart
                x={result.fan.p50.map((_, i) => i)}
                bands={[
                  {
                    key: "outer",
                    label: "5–95%",
                    lo: result.fan.p05,
                    hi: result.fan.p95,
                    color: "var(--primary)",
                    opacity: 0.12,
                  },
                  {
                    key: "inner",
                    label: "25–75%",
                    lo: result.fan.p25,
                    hi: result.fan.p75,
                    color: "var(--primary)",
                    opacity: 0.25,
                  },
                ]}
                series={[
                  {
                    key: "median",
                    label: "Median",
                    values: result.fan.p50,
                    color: "var(--primary)",
                    width: 2,
                  },
                  ...result.samples.slice(0, 4).map((s, i) => ({
                    key: `s${i}`,
                    label: i === 0 ? "Sample paths" : `Sample ${i + 1}`,
                    values: s,
                    color: "var(--muted-foreground)",
                    width: 1,
                    ghost: true,
                  })),
                ]}
                height={300}
                xFormat={(i) => `day ${Math.round(i)}`}
                yFormat={(v) => `$${v.toFixed(2)}`}
                label="Monte Carlo equity fan"
              />
            </Panel>
            <Panel
              title="Sharpe across paths"
              icon={Sigma}
              subtitle="Distribution of realised Sharpe"
            >
              <SharpeHistogram sharpes={result.sharpes} />
            </Panel>
          </div>
        </>
      )}

      <p className="mt-6 border-t pt-3 text-[11px] text-muted-foreground">
        Illustrative results for demonstration purposes only.
      </p>
    </div>
  );
}

function SharpeHistogram({ sharpes }: { sharpes: number[] }) {
  const lo = Math.floor(Math.min(...sharpes) * 2) / 2;
  const hi = Math.ceil(Math.max(...sharpes) * 2) / 2;
  const edges: number[] = [];
  for (let e = lo; e < hi; e += 0.5) edges.push(e);
  const counts = edges.map((e) => sharpes.filter((s) => s >= e && s < e + 0.5).length);
  return (
    <BarChart
      categories={edges.map((e) => e.toFixed(1))}
      groups={[{ key: "n", label: "Paths", color: "var(--primary)", values: counts }]}
      height={300}
      yFormat={(v) => v.toFixed(0)}
      label="Histogram of Sharpe ratios across Monte Carlo paths"
    />
  );
}

function Choice({
  legend,
  options,
  value,
  onChange,
}: {
  legend: string;
  options: [string, string][];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <fieldset>
      <legend className="mb-2 text-xs text-muted-foreground">{legend}</legend>
      <div className="flex flex-wrap gap-1" role="radiogroup" aria-label={legend}>
        {options.map(([v, label]) => (
          <button
            key={v}
            type="button"
            role="radio"
            aria-checked={value === v}
            onClick={() => onChange(v)}
            className={cn(
              "rounded-md border px-2.5 py-1 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
              value === v ? "border-primary bg-primary/10" : "bg-surface-2/40",
            )}
          >
            {label}
          </button>
        ))}
      </div>
    </fieldset>
  );
}
