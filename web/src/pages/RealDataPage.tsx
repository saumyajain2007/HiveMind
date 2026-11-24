import {
  Brain,
  CalendarClock,
  Landmark,
  Scale,
  Target,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { useMemo, useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { XYChart } from "@/components/charts/XYChart";
import { Panel } from "@/components/Panel";
import { Stat } from "@/components/Stat";
import { Skeleton } from "@/components/ui/skeleton";
import { MODEL_LABEL, MODELS } from "@/lib/api/experiments";
import type { ExperimentResults, ModelKey, OriginRow, SliceStats } from "@/lib/api/experiments";
import { useExperiment, useExperiments } from "@/lib/api/queries";
import { formatPct, formatSignedPct } from "@/lib/format";
import { cn } from "@/lib/utils";

const COLOR: Record<ModelKey, string> = {
  random_walk: "var(--muted-foreground)",
  event_random_walk: "var(--fundamental)",
  abm_raw: "var(--official)",
  abm: "var(--primary)",
  abm_oracle: "var(--narrative)",
};

const WINDOWS = [
  ["all", "Whole test period"],
  ["250", "Last 250 forecasts"],
  ["60", "Last 60 forecasts"],
] as const;

const tab =
  "inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/60";

function Skill({ value }: { value: number | undefined }) {
  if (value == null) return <span className="text-muted-foreground">–</span>;
  return (
    <span
      className={cn(
        "tabular-nums",
        value > 0.005 ? "text-bull-text" : value < -0.005 ? "text-bear-text" : "",
      )}
    >
      {formatSignedPct(value, 1)}
    </span>
  );
}

const move = (r: OriginRow, m: ModelKey, k: "q05" | "q95" | "median") => r[m][k] / r.close - 1;

function Interval({ r, m }: { r: OriginRow; m: ModelKey }) {
  const inside = r[m].q05 <= r.actual && r.actual <= r[m].q95;
  return (
    <span className={cn("tabular-nums", !inside && "text-bear-text")}>
      {formatSignedPct(move(r, m, "q05"), 1)} … {formatSignedPct(move(r, m, "q95"), 1)}
    </span>
  );
}

function rolling(rows: OriginRow[], m: ModelKey, w: number): (number | null)[] {
  const out: (number | null)[] = [];
  let a = 0;
  let b = 0;
  for (let i = 0; i < rows.length; i++) {
    a += rows[i]![m].crps;
    b += rows[i]!.random_walk.crps;
    if (i >= w) {
      a -= rows[i - w]![m].crps;
      b -= rows[i - w]!.random_walk.crps;
    }
    out.push(i >= w - 1 && b > 0 ? 1 - a / b : null);
  }
  return out;
}

function SummaryTable({ s }: { s: Record<string, SliceStats> }) {
  const slices = [
    ["all", "All days"],
    ["earnings_in_horizon", "Earnings in horizon"],
    ["no_earnings", "Other days"],
  ] as const;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-sm">
        <thead>
          <tr className="border-b text-left text-xs text-muted-foreground">
            <th className="py-2 font-medium">Model</th>
            <th className="py-2 text-right font-medium">CRPS, % of price</th>
            <th className="py-2 text-right font-medium">Skill vs random walk</th>
            {slices.slice(1).map(([k, l]) => (
              <th key={k} className="py-2 text-right font-medium">
                Skill, {l.toLowerCase()} (n={s[k]?.n ?? 0})
              </th>
            ))}
            <th className="py-2 text-right font-medium">90% coverage</th>
            <th className="py-2 text-right font-medium">Direction</th>
          </tr>
        </thead>
        <tbody>
          {MODELS.map((m) => {
            const a = s.all?.[m];
            return (
              <tr key={m} className="border-b last:border-0">
                <td className="py-2">
                  <span
                    className="mr-2 inline-block size-2.5 rounded-full"
                    style={{ background: COLOR[m] }}
                    aria-hidden
                  />
                  {MODEL_LABEL[m]}
                </td>
                <td className="py-2 text-right tabular-nums">{a?.mean_crps_pct.toFixed(3)}</td>
                <td className="py-2 text-right">
                  {m === "random_walk" ? "baseline" : <Skill value={a?.skill_vs_random_walk} />}
                </td>
                {slices.slice(1).map(([k]) => (
                  <td key={k} className="py-2 text-right">
                    {m === "random_walk" ? (
                      "baseline"
                    ) : (
                      <Skill value={s[k]?.[m]?.skill_vs_random_walk} />
                    )}
                  </td>
                ))}
                <td
                  className={cn(
                    "py-2 text-right tabular-nums",
                    a && Math.abs(a.coverage_90 - 0.9) > 0.08 && "text-bear-text",
                  )}
                >
                  {formatPct(a?.coverage_90, 0)}
                </td>
                <td className="py-2 text-right tabular-nums">
                  {formatPct(a?.direction_accuracy, 0)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Results({ res }: { res: ExperimentResults }) {
  const horizons = Object.keys(res.backtest).sort((a, b) => Number(a) - Number(b));
  const [h, setH] = useState(horizons[0] ?? "1");
  const [win, setWin] = useState<(typeof WINDOWS)[number][0]>("250");
  const b = res.backtest[h] ?? res.backtest[horizons[0]!]!;
  const all = b.origins;
  const rows = useMemo(() => (win === "all" ? all : all.slice(-Number(win))), [all, win]);
  const x = useMemo(() => rows.map((_, i) => i), [rows]);
  const rollW = Math.min(60, Math.max(10, Math.floor(all.length / 6)));
  const roll = useMemo(
    () =>
      (["event_random_walk", "abm_raw", "abm", "abm_oracle"] as const).map((m) => ({
        m,
        v: rolling(all, m, rollW),
      })),
    [all, rollW],
  );
  const biggest = useMemo(
    () =>
      [...all]
        .sort(
          (p, q) =>
            Math.abs(q.abm.crps - q.random_walk.crps) - Math.abs(p.abm.crps - p.random_walk.crps),
        )
        .slice(0, 12),
    [all],
  );
  const earnings = all.filter((r) => r.earnings_in_horizon);
  const im = res.impact_model;
  const events = useMemo(
    () =>
      [...(im.events ?? [])].sort((p, q) => Math.abs(q.actual) - Math.abs(p.actual)).slice(0, 15),
    [im.events],
  );
  const abm = b.summary.all.abm;
  const erw = b.summary.all.event_random_walk;
  const raw = b.summary.all.abm_raw;
  const recal = res.simulation.recalibration?.[h];

  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        <div
          className="flex gap-1 rounded-lg border bg-card p-1"
          role="tablist"
          aria-label="Forecast horizon"
        >
          {horizons.map((k) => (
            <button
              key={k}
              type="button"
              role="tab"
              aria-selected={h === k}
              onClick={() => setH(k)}
              className={cn(
                tab,
                h === k
                  ? "bg-primary/12 font-medium"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {k} day{k === "1" ? "" : "s"} ahead
            </button>
          ))}
        </div>
        <p className="text-sm text-muted-foreground">
          {b.summary.all.n} out-of-sample forecasts · each made at a close, scored on the close {h}{" "}
          trading day
          {h === "1" ? "" : "s"} later
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label="Agent model skill vs random walk"
          value={abm ? abm.skill_vs_random_walk * 100 : null}
          format={(v) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}%`}
          hint={`recalibrated; raw ensemble ${formatSignedPct(raw?.skill_vs_random_walk, 1)}`}
        />
        <Stat
          label="Event-aware random walk skill"
          value={erw ? erw.skill_vs_random_walk * 100 : null}
          format={(v) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}%`}
          hint="random walk + the classifier's predicted jumps"
        />
        <Stat
          label="Agent model 90% coverage"
          value={abm ? abm.coverage_90 * 100 : null}
          format={(v) => `${v.toFixed(0)}%`}
          hint="share of actual closes inside the 90% band (target 90%)"
        />
        <Stat
          label="Agent model direction accuracy"
          value={abm ? abm.direction_accuracy * 100 : null}
          format={(v) => `${v.toFixed(0)}%`}
          hint="P(up) > 50% vs the real sign; a coin flip is ~50%"
        />
      </div>

      <Panel
        title="Every model, out of sample"
        icon={Scale}
        subtitle="CRPS: lower is better. Skill = 1 − CRPS / random-walk CRPS"
      >
        <SummaryTable s={b.summary} />
        <p className="mt-3 text-xs text-muted-foreground">
          Raw: the simulation&apos;s runs as they come. Recalibrated: the same runs after a
          correction fitted on the training years only
          {recal
            ? ` (centre × ${recal.shrink.toFixed(2)}, spread × ${recal.spread.toFixed(2)}, plus ${recal.vol_weight.toFixed(2)} × trailing volatility)`
            : ""}
          . Oracle: told every event&apos;s true reaction in advance, so it is an upper bound, not a
          forecast.
          {im.jump_scale != null &&
            ` Predicted earnings jumps are scaled by ${im.jump_scale} (fitted on training releases).`}
        </p>
      </Panel>

      <Panel
        title="Forecast bands against what happened"
        icon={Target}
        subtitle={`Move over ${h} day${h === "1" ? "" : "s"} · bands: 90% intervals · line: the real move · ticks: earnings in the horizon`}
        actions={
          <select
            aria-label="Window"
            className="h-8 rounded-md border bg-surface-2 px-2 text-sm"
            value={win}
            onChange={(e) => setWin(e.target.value as typeof win)}
          >
            {WINDOWS.map(([k, l]) => (
              <option key={k} value={k}>
                {l}
              </option>
            ))}
          </select>
        }
      >
        <XYChart
          x={x}
          series={[
            {
              key: "actual",
              label: "Actual move",
              values: rows.map((r) => r.actual_return * 100),
              color: "var(--foreground)",
              width: 1.5,
            },
            {
              key: "abm",
              label: "Agent model, median",
              values: rows.map((r) => move(r, "abm", "median") * 100),
              color: COLOR.abm,
              dash: "4 3",
            },
          ]}
          bands={[
            {
              key: "rw",
              label: "Random walk 90%",
              lo: rows.map((r) => move(r, "random_walk", "q05") * 100),
              hi: rows.map((r) => move(r, "random_walk", "q95") * 100),
              color: COLOR.random_walk,
              opacity: 0.18,
            },
            {
              key: "abm90",
              label: "Agent model 90%",
              lo: rows.map((r) => move(r, "abm", "q05") * 100),
              hi: rows.map((r) => move(r, "abm", "q95") * 100),
              color: COLOR.abm,
              opacity: 0.22,
            },
          ]}
          markers={rows.flatMap((r, i) =>
            r.earnings_in_horizon
              ? [
                  {
                    x: i,
                    label: `Earnings ${r.target}`,
                    color: "var(--muted-foreground)",
                    tag: "E",
                  },
                ]
              : [],
          )}
          zeroLine={0}
          height={320}
          xFormat={(i) => rows[Math.round(i)]?.target ?? ""}
          yFormat={(v) => `${v.toFixed(1)}%`}
          label="Actual move and each model's 90% forecast band at every test origin"
        />
      </Panel>

      <Panel
        title="Where the models differ over time"
        icon={CalendarClock}
        subtitle={`Rolling skill vs the random walk, ${rollW} forecasts wide · above zero: better than the random walk`}
      >
        <XYChart
          x={all.map((_, i) => i)}
          series={roll.map(({ m, v }) => ({
            key: m,
            label: MODEL_LABEL[m],
            values: v.map((y) => (y == null ? null : y * 100)),
            color: COLOR[m],
          }))}
          zeroLine={0}
          height={240}
          xFormat={(i) => all[Math.round(i)]?.target ?? ""}
          yFormat={(v) => `${v.toFixed(0)}%`}
          label="Rolling CRPS skill of each model against the random walk"
        />
      </Panel>

      <Panel
        title="Biggest differences: agent model vs random walk"
        icon={Scale}
        subtitle="The 12 forecasts where their CRPS differs most · red interval: the actual move fell outside it"
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="py-2 font-medium">Origin → target</th>
                <th className="py-2 text-right font-medium">Actual</th>
                <th className="py-2 text-right font-medium">Random walk 90%</th>
                <th className="py-2 text-right font-medium">Agent model 90%</th>
                <th className="py-2 text-right font-medium">P(up)</th>
                <th className="py-2 text-right font-medium">Better</th>
                <th className="py-2 pl-4 font-medium">Earnings</th>
              </tr>
            </thead>
            <tbody>
              {biggest.map((r) => {
                const win = r.abm.crps < r.random_walk.crps;
                return (
                  <tr key={r.origin} className="border-b last:border-0">
                    <td className="py-2 font-mono text-xs">
                      {r.origin} → {r.target}
                    </td>
                    <td className="py-2 text-right tabular-nums">
                      {formatSignedPct(r.actual_return, 1)}
                    </td>
                    <td className="py-2 text-right">
                      <Interval r={r} m="random_walk" />
                    </td>
                    <td className="py-2 text-right">
                      <Interval r={r} m="abm" />
                    </td>
                    <td className="py-2 text-right tabular-nums">{formatPct(r.abm.p_up, 0)}</td>
                    <td
                      className={cn("py-2 text-right", win ? "text-bull-text" : "text-bear-text")}
                    >
                      {win ? "Agent model" : "Random walk"}
                    </td>
                    <td className="py-2 pl-4">{r.earnings_in_horizon ? "Yes" : ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      {earnings.length > 0 && (
        <Panel
          title="Every forecast with earnings in the horizon"
          icon={Landmark}
          subtitle="Scheduled releases: the forecasters know the date, not the numbers"
        >
          <div
            className="max-h-[420px] overflow-auto rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            tabIndex={0}
            role="region"
            aria-label="Forecasts with earnings in the horizon"
          >
            <table className="w-full min-w-[880px] text-sm">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-2 font-medium">Target</th>
                  <th className="py-2 text-right font-medium">Actual</th>
                  <th className="py-2 text-right font-medium">Random walk 90%</th>
                  <th className="py-2 text-right font-medium">Event-aware RW 90%</th>
                  <th className="py-2 text-right font-medium">Agent model 90%</th>
                  <th className="py-2 text-right font-medium">Oracle median</th>
                  <th className="py-2 text-right font-medium">Best</th>
                </tr>
              </thead>
              <tbody>
                {earnings.map((r) => {
                  const best = (["random_walk", "event_random_walk", "abm"] as const).reduce(
                    (p, q) => (r[q].crps < r[p].crps ? q : p),
                  );
                  return (
                    <tr key={r.origin} className="border-b last:border-0">
                      <td className="py-2 font-mono text-xs">{r.target}</td>
                      <td className="py-2 text-right tabular-nums">
                        {formatSignedPct(r.actual_return, 1)}
                      </td>
                      <td className="py-2 text-right">
                        <Interval r={r} m="random_walk" />
                      </td>
                      <td className="py-2 text-right">
                        <Interval r={r} m="event_random_walk" />
                      </td>
                      <td className="py-2 text-right">
                        <Interval r={r} m="abm" />
                      </td>
                      <td className="py-2 text-right tabular-nums">
                        {formatSignedPct(move(r, "abm_oracle", "median"), 1)}
                      </td>
                      <td className="py-2 text-right">{MODEL_LABEL[best]}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      <Panel
        title="The event classifier"
        icon={Brain}
        subtitle={`Multinomial logistic (down / flat / up, ±1%) + ridge on log size · trained on ${im.n_train} filings, tested on ${im.n_test} later ones`}
      >
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat
            label="Class accuracy"
            value={im.test.accuracy * 100}
            format={(v) => `${v.toFixed(0)}%`}
            hint={`always-majority: ${formatPct(im.test.majority_accuracy, 0)}`}
          />
          <Stat
            label="Direction on real moves"
            value={im.test.direction_hit_rate * 100}
            format={(v) => `${v.toFixed(0)}%`}
            hint={`of ${im.test.n_moves} moves beyond ±1%`}
          />
          <Stat
            label="Size correlation"
            value={im.test.size_corr}
            format={(v) => v.toFixed(2)}
            hint="predicted vs actual log |move|"
          />
          <Stat
            label="Size error (log)"
            value={im.test.size_mae_log}
            format={(v) => v.toFixed(2)}
            hint={`constant guess: ${im.test.constant_size_mae_log.toFixed(2)}`}
          />
        </div>
        {events.length > 0 && (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <caption className="pb-2 text-left text-xs text-muted-foreground">
                The 15 biggest test-period reactions, with what the classifier predicted beforehand
              </caption>
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-2 font-medium">Reaction day</th>
                  <th className="py-2 font-medium">Filing</th>
                  <th className="py-2 text-right font-medium">Actual</th>
                  <th className="py-2 text-right font-medium">P(down / flat / up)</th>
                  <th className="py-2 text-right font-medium">Predicted size</th>
                  <th className="py-2 pl-4 font-medium">Called the direction</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e) => {
                  const call = e.p_up >= e.p_down ? 1 : -1;
                  const hit = Math.sign(e.actual) === call;
                  return (
                    <tr
                      key={`${e.date}-${e.form}-${e.items.join()}`}
                      className="border-b last:border-0"
                    >
                      <td className="py-2 font-mono text-xs">{e.date}</td>
                      <td className="py-2">
                        {e.form} {e.items.join(", ")}{" "}
                        <span className="text-muted-foreground">({e.group.replace("_", " ")})</span>
                      </td>
                      <td className="py-2 text-right tabular-nums">
                        {formatSignedPct(e.actual, 1)}
                      </td>
                      <td className="py-2 text-right tabular-nums">
                        {formatPct(e.p_down, 0)} / {formatPct(e.p_flat, 0)} / {formatPct(e.p_up, 0)}
                      </td>
                      <td className="py-2 text-right tabular-nums">
                        ±{(e.size * 100).toFixed(1)}%
                      </td>
                      <td className="py-2 pl-4">
                        <span
                          className={cn(
                            "inline-flex items-center gap-1",
                            hit ? "text-bull-text" : "text-bear-text",
                          )}
                        >
                          {call > 0 ? (
                            <TrendingUp className="size-4" aria-hidden />
                          ) : (
                            <TrendingDown className="size-4" aria-hidden />
                          )}
                          {hit ? "Yes" : "No"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  );
}

export function RealDataPage() {
  const list = useExperiments();
  const [ticker, setTicker] = useState<string | null>(null);
  const chosen = ticker ?? list.data?.[0]?.ticker ?? null;
  const exp = useExperiment(chosen);
  const res = exp.data;
  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-5 p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-mono text-[11px] tracking-[0.16em] text-primary">REAL DATA</p>
          <h2 className="mt-1 text-2xl font-semibold tracking-tight">
            {res ? `${res.ticker} · ${res.name}` : "Real stocks, real events"}
          </h2>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            {res
              ? `Trained on ${res.period.train[0]} to ${res.period.train[1]}, tested on ${res.period.test[0]} to ${res.period.test[1]}. ${res.events.total} SEC filings as events (${res.events.train} train, ${res.events.test} test).`
              : "Every SEC filing as an event, a classifier for each event's impact, and the agent model forecasting the next closes out of sample."}
          </p>
        </div>
        {(list.data?.length ?? 0) > 1 && (
          <select
            aria-label="Stock"
            className="h-8 rounded-md border bg-surface-2 px-2 text-sm"
            value={chosen ?? ""}
            onChange={(e) => setTicker(e.target.value)}
          >
            {list.data?.map((x) => (
              <option key={x.ticker} value={x.ticker}>
                {x.ticker}
              </option>
            ))}
          </select>
        )}
      </div>
      {list.isLoading || exp.isLoading ? (
        <Skeleton className="h-72" />
      ) : !res ? (
        <EmptyState
          icon={Landmark}
          title="No experiments yet"
          description="Run: uv run python scripts/fetch_market_data.py AAPL, then uv run python -m marketsim.experiment AAPL"
        />
      ) : (
        <Results res={res} />
      )}
    </div>
  );
}
