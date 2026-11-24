import {
  CalendarClock,
  Gauge,
  LineChart,
  Sigma,
  Target,
  TriangleAlert,
  WalletCards,
} from "lucide-react";
import { useMemo, useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { XYChart } from "@/components/charts/XYChart";
import { Panel } from "@/components/Panel";
import { Stat } from "@/components/Stat";
import { Skeleton } from "@/components/ui/skeleton";
import type { Fitness, ForecastSummary, StrategyDoc } from "@/lib/api/experiments";
import { useExperiments, useStrategy } from "@/lib/api/queries";
import { formatPct, formatPrice, formatSigned, formatSignedPct } from "@/lib/format";
import { cn } from "@/lib/utils";

const STRAT_COLOR: Record<string, string> = {
  buy_hold: "var(--foreground)",
  model_long_short: "var(--bear)",
  model_long_flat: "var(--primary)",
  vol_target_model: "var(--bull)",
  vol_target_trailing: "var(--muted-foreground)",
  earnings_classifier: "var(--narrative)",
};

const WINDOWS = [
  ["60", "Last 60 days"],
  ["250", "Last 250 days"],
  ["all", "Whole test period"],
] as const;

const tab =
  "inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/60";
const th = "py-2 text-right font-medium";
const td = "py-2 text-right tabular-nums";

function Signed({ v, digits = 1, pct = true }: { v: number; digits?: number; pct?: boolean }) {
  return (
    <span className={cn(v > 0 ? "text-bull-text" : v < 0 ? "text-bear-text" : "")}>
      {pct ? formatSignedPct(v, digits) : formatSigned(v, digits)}
    </span>
  );
}

function LatestForecast({ doc }: { doc: StrategyDoc }) {
  const lt = doc.latest;
  return (
    <Panel
      title={`Forecast from the last close (${lt.date}: ${formatPrice(lt.close)})`}
      icon={Target}
      subtitle="Agent model, recalibrated: the distribution of the close on the target day"
    >
      <div className="grid gap-4 lg:grid-cols-2">
        {Object.entries(lt.horizons).map(([h, f]) => (
          <div key={h} className="rounded-lg border bg-surface-2/40 p-4">
            <p className="text-sm font-medium">
              {h} trading day{h === "1" ? "" : "s"} ahead · {f.target}
              {f.scheduled_earnings > 0 && (
                <span className="ml-2 text-xs text-muted-foreground">earnings in the window</span>
              )}
            </p>
            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat
                label="Expected price"
                value={f.mean}
                format={(v) => formatPrice(v)}
                hint="mean"
              />
              <Stat
                label="Std. deviation"
                value={f.sd}
                format={(v) => formatPrice(v)}
                hint={`RW ${formatPrice(f.random_walk_sd)}`}
              />
              <Stat
                label="Expected return"
                value={f.expected_return * 100}
                format={(v) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}%`}
              />
              <Stat
                label="P(close higher)"
                value={f.p_up * 100}
                format={(v) => `${v.toFixed(0)}%`}
              />
            </div>
            <table className="mt-3 w-full text-sm">
              <caption className="sr-only">Quantiles of the forecast price</caption>
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  {["5%", "25%", "Median", "75%", "95%"].map((q) => (
                    <th key={q} className={th}>
                      {q}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  {[f.q05, f.q25, f.q50, f.q75, f.q95].map((v, i) => (
                    <td key={i} className={td}>
                      {formatPrice(v)}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
            <p className="mt-2 text-xs text-muted-foreground">
              Simulated runs: {f.runs.length}, from {formatPrice(Math.min(...f.runs))} to{" "}
              {formatPrice(Math.max(...f.runs))}
            </p>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function ForecastStats({ s }: { s: ForecastSummary }) {
  const rows: [string, string, string, string][] = [
    ["Forecasts", String(s.n), String(s.n), ""],
    ["Mean actual return", formatSignedPct(s.mean_actual_return, 3), "", ""],
    ["Mean expected return", formatSignedPct(s.mean_expected_return, 3), "0 by design", ""],
    [
      "Bias (actual − expected)",
      formatSignedPct(s.bias, 3),
      formatSignedPct(s.mean_actual_return, 3),
      "close to 0",
    ],
    [
      "RMSE of the expected return",
      formatPct(s.rmse_model, 3),
      formatPct(s.rmse_random_walk, 3),
      "lower",
    ],
    [
      "MAE of the expected return",
      formatPct(s.mae_model, 3),
      formatPct(s.mae_random_walk, 3),
      "lower",
    ],
    [
      "Information coefficient (t)",
      `${formatSigned(s.information_coefficient, 3)} (${formatSigned(s.ic_t, 2)})`,
      "0",
      "> 0, |t| > 2",
    ],
    ["Direction hit rate", formatPct(s.sign_hit_rate, 1), "–", "> 50%"],
    [
      "Forecast sd, mean (log)",
      formatPct(s.mean_forecast_sd, 2),
      formatPct(s.mean_rw_sd, 2),
      `realised: ${formatPct(s.realised_rms, 2)}`,
    ],
    [
      "z-score mean / sd",
      `${formatSigned(s.z_mean, 2)} / ${s.z_sd.toFixed(2)}`,
      `${formatSigned(s.rw_z_mean, 2)} / ${s.rw_z_sd.toFixed(2)}`,
      "0 / 1",
    ],
    ["50% interval coverage", formatPct(s.coverage_50, 0), formatPct(s.rw_coverage_50, 0), "50%"],
    ["90% interval coverage", formatPct(s.coverage_90, 0), formatPct(s.rw_coverage_90, 0), "90%"],
    [
      "Volatility skill: corr(sd, |move|)",
      s.vol_skill_model.toFixed(3),
      s.vol_skill_random_walk.toFixed(3),
      "higher",
    ],
  ];
  return (
    <div
      className="overflow-x-auto rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
      tabIndex={0}
      role="region"
      aria-label="Forecast statistics table"
    >
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b text-left text-xs text-muted-foreground">
            <th className="py-2 font-medium">Statistic</th>
            <th className={th}>Agent model</th>
            <th className={th}>Random walk</th>
            <th className={th}>Ideal</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([k, a, b, c]) => (
            <tr key={k} className="border-b last:border-0">
              <td className="py-2">{k}</td>
              <td className={td}>{a}</td>
              <td className={td}>{b}</td>
              <td className={cn(td, "text-muted-foreground")}>{c}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FitnessPanel({ fitness }: { fitness: NonNullable<StrategyDoc["fitness"]> }) {
  const rows: [string, (f: Fitness) => string][] = [
    ["Forecasts", (f) => String(f.n)],
    [
      "Information coefficient (t)",
      (f) => `${formatSigned(f.information_coefficient, 3)} (${formatSigned(f.ic_t, 1)})`,
    ],
    ["Rank IC", (f) => formatSigned(f.rank_ic, 3)],
    ["Direction hit rate", (f) => formatPct(f.hit_rate, 1)],
    [
      "Brier score (climatology)",
      (f) => `${f.brier.toFixed(4)} (${f.brier_climatology.toFixed(4)})`,
    ],
    [
      "Log loss (climatology)",
      (f) => `${f.log_loss.toFixed(4)} (${f.log_loss_climatology.toFixed(4)})`,
    ],
  ];
  const hs = Object.keys(fitness).sort((a, b) => Number(a) - Number(b));
  return (
    <Panel
      title="Model fitness: training vs test"
      icon={Sigma}
      subtitle="Training: the origins the recalibration was fitted on (in sample). Test: every later day (out of sample). A gap is overfitting."
    >
      <div
        className="overflow-x-auto rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
        tabIndex={0}
        role="region"
        aria-label="Model fitness table"
      >
        <table className="w-full min-w-[760px] text-sm">
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground">
              <th className="py-2 font-medium">Statistic</th>
              {hs.flatMap((h) => [
                <th key={`${h}tr`} className={th}>
                  {h}-day, training
                </th>,
                <th key={`${h}te`} className={th}>
                  {h}-day, test
                </th>,
              ])}
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, fmt]) => (
              <tr key={label} className="border-b last:border-0">
                <td className="py-2">{label}</td>
                {hs.flatMap((h) => [
                  <td key={`${h}tr`} className={cn(td, "text-muted-foreground")}>
                    {fmt(fitness[h]!.train)}
                  </td>,
                  <td key={`${h}te`} className={cn(td, "font-medium")}>
                    {fmt(fitness[h]!.test)}
                  </td>,
                ])}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function Verdict({ doc }: { doc: StrategyDoc }) {
  const res = doc.strategy.results;
  const bh = res.buy_hold;
  const others = Object.entries(res).filter(([k]) => k !== "buy_hold");
  const best = others.reduce((a, b) => (b[1].sharpe > a[1].sharpe ? b : a));
  const beats = bh && best[1].sharpe > bh.sharpe && best[1].p_sharpe_not_above_buy_hold < 0.05;
  const ic = doc.forecasts["1"]?.summary;
  return (
    <div
      role="note"
      className={cn(
        "flex gap-3 rounded-lg border p-4 text-sm",
        beats ? "border-bull/40 bg-bull/5" : "border-status-warning/40 bg-status-warning/5",
      )}
    >
      <TriangleAlert className="mt-0.5 size-5 shrink-0" aria-hidden />
      <div>
        <p className="font-medium">
          {beats
            ? `${best[1].label} beats buy and hold with statistical confidence.`
            : "No strategy beats buy and hold with statistical confidence."}
        </p>
        <p className="mt-1 text-muted-foreground">
          Best Sharpe: {best[1].label}, {best[1].sharpe.toFixed(2)} (95% CI{" "}
          {best[1].sharpe_ci95[0].toFixed(2)} to {best[1].sharpe_ci95[1].toFixed(2)}) vs buy and
          hold {bh?.sharpe.toFixed(2)}; the chance its Sharpe is not above buy and hold is{" "}
          {formatPct(best[1].p_sharpe_not_above_buy_hold, 0)}.
          {ic &&
            ` The model's one-day expected return has an information coefficient of ${formatSigned(ic.information_coefficient, 3)} (t ${formatSigned(ic.ic_t, 2)}): no usable directional signal. Its spread forecast tracks the size of the next move slightly better than trailing volatility (${ic.vol_skill_model.toFixed(2)} vs ${ic.vol_skill_random_walk.toFixed(2)}).`}{" "}
          Every rule was fixed before looking at the test period; costs of {doc.strategy.cost_bps}{" "}
          bp per unit of turnover are included. Not investment advice.
        </p>
      </div>
    </div>
  );
}

function Body({ doc }: { doc: StrategyDoc }) {
  const horizons = Object.keys(doc.forecasts).sort((a, b) => Number(a) - Number(b));
  const [h, setH] = useState(horizons[0] ?? "1");
  const [win, setWin] = useState<(typeof WINDOWS)[number][0]>("60");
  const fc = doc.forecasts[h] ?? doc.forecasts[horizons[0]!]!;
  const rows = useMemo(() => (win === "all" ? fc.rows : fc.rows.slice(-Number(win))), [fc, win]);
  const x = useMemo(() => rows.map((_, i) => i), [rows]);
  const st = doc.strategy;
  const strat = Object.entries(st.results);
  const recent = fc.rows.slice(-15).reverse();
  return (
    <>
      <Verdict doc={doc} />
      <LatestForecast doc={doc} />

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
          {fc.summary.n} out-of-sample forecasts, {doc.period.test[0]} to {doc.period.test[1]}
        </p>
      </div>

      <Panel
        title="Expected price against the real close"
        icon={LineChart}
        subtitle="Line: real close on the target day · dashed: the model's expected price · bands: 50% and 90% ranges"
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
              label: "Real close",
              values: rows.map((r) => r.actual),
              color: "var(--foreground)",
              width: 1.5,
            },
            {
              key: "mean",
              label: "Expected (mean)",
              values: rows.map((r) => r.mean),
              color: "var(--primary)",
              dash: "4 3",
            },
          ]}
          bands={[
            {
              key: "b90",
              label: "90% range",
              lo: rows.map((r) => r.q05),
              hi: rows.map((r) => r.q95),
              color: "var(--primary)",
              opacity: 0.12,
            },
            {
              key: "b50",
              label: "50% range",
              lo: rows.map((r) => r.q25),
              hi: rows.map((r) => r.q75),
              color: "var(--primary)",
              opacity: 0.22,
            },
          ]}
          height={320}
          xFormat={(i) => rows[Math.round(i)]?.target ?? ""}
          yFormat={(v) => formatPrice(v, 0)}
          label="Real close and the model's expected price with 50% and 90% ranges"
        />
      </Panel>

      <Panel
        title="Forecast statistics"
        icon={Sigma}
        subtitle="How the forecasts compare with what happened, next to the random walk"
      >
        <ForecastStats s={fc.summary} />
      </Panel>

      <Panel
        title="Recent forecasts"
        icon={CalendarClock}
        subtitle="The latest 15 test forecasts · z: (actual − forecast centre) / forecast sd, in log terms"
      >
        <div
          className="overflow-x-auto rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          tabIndex={0}
          role="region"
          aria-label="Recent forecasts table"
        >
          <table className="w-full min-w-[880px] text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="py-2 font-medium">Target</th>
                <th className={th}>Close at origin</th>
                <th className={th}>Expected</th>
                <th className={th}>Sd</th>
                <th className={th}>90% range</th>
                <th className={th}>P(up)</th>
                <th className={th}>Actual</th>
                <th className={th}>Error</th>
                <th className={th}>z</th>
              </tr>
            </thead>
            <tbody>
              {recent.map((r) => {
                const inside = r.q05 <= r.actual && r.actual <= r.q95;
                return (
                  <tr key={r.origin} className="border-b last:border-0">
                    <td className="py-2 font-mono text-xs">{r.target}</td>
                    <td className={td}>{formatPrice(r.close)}</td>
                    <td className={td}>{formatPrice(r.mean)}</td>
                    <td className={td}>{formatPrice(r.sd)}</td>
                    <td className={cn(td, !inside && "text-bear-text")}>
                      {formatPrice(r.q05)} – {formatPrice(r.q95)}
                    </td>
                    <td className={td}>{formatPct(r.p_up, 0)}</td>
                    <td className={td}>{formatPrice(r.actual)}</td>
                    <td className={td}>
                      <Signed v={r.actual / r.mean - 1} digits={2} />
                    </td>
                    <td className={td}>{formatSigned(r.z, 2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel
        title="Trading strategies built on the model"
        icon={WalletCards}
        subtitle={`Daily, ${st.start} to ${doc.period.test[1]} · positions set at each close, held to the next · ${st.cost_bps} bp cost per unit of turnover`}
      >
        <div
          className="overflow-x-auto rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          tabIndex={0}
          role="region"
          aria-label="Strategy results table"
        >
          <table className="w-full min-w-[1320px] text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="py-2 font-medium">Strategy</th>
                <th className={th}>Total return</th>
                <th className={th}>CAGR</th>
                <th className={th}>Volatility</th>
                <th className={th}>Sharpe (95% CI)</th>
                <th className={th}>Sortino</th>
                <th className={th}>Max drawdown</th>
                <th className={th}>Alpha / yr (t)</th>
                <th className={th}>Beta</th>
                <th className={th}>Hit rate</th>
                <th className={th}>Turnover / yr</th>
                <th className={th}>Trades</th>
                <th className={th}>Win rate</th>
                <th className={th}>Profit factor</th>
                <th className={th}>PSR</th>
                <th className={th}>DSR</th>
              </tr>
            </thead>
            <tbody>
              {strat.map(([k, s]) => (
                <tr key={k} className="border-b align-top last:border-0">
                  <td className="py-2 pr-4">
                    <span
                      className="mr-2 inline-block size-2.5 rounded-full"
                      style={{ background: STRAT_COLOR[k] ?? "var(--muted-foreground)" }}
                      aria-hidden
                    />
                    {s.label}
                    <p className="mt-0.5 max-w-[340px] text-xs text-muted-foreground">
                      {s.description}
                    </p>
                  </td>
                  <td className={td}>
                    <Signed v={s.total_return} />
                  </td>
                  <td className={td}>
                    <Signed v={s.cagr} />
                  </td>
                  <td className={td}>{formatPct(s.ann_vol, 1)}</td>
                  <td className={td}>
                    {s.sharpe.toFixed(2)}{" "}
                    <span className="text-xs text-muted-foreground">
                      ({s.sharpe_ci95[0].toFixed(2)} to {s.sharpe_ci95[1].toFixed(2)})
                    </span>
                  </td>
                  <td className={td}>{s.sortino.toFixed(2)}</td>
                  <td className={td}>{formatPct(s.max_drawdown, 1)}</td>
                  <td className={td}>
                    <Signed v={s.alpha_ann} />{" "}
                    <span className="text-xs text-muted-foreground">
                      ({formatSigned(s.alpha_t, 1)})
                    </span>
                  </td>
                  <td className={td}>{s.beta.toFixed(2)}</td>
                  <td className={td}>{formatPct(s.hit_rate, 0)}</td>
                  <td className={td}>{s.turnover_per_year.toFixed(0)}×</td>
                  <td className={td}>{s.n_trades ?? "–"}</td>
                  <td className={td}>{s.win_rate == null ? "–" : formatPct(s.win_rate, 0)}</td>
                  <td className={td}>
                    {s.profit_factor == null ? "–" : s.profit_factor.toFixed(2)}
                  </td>
                  <td className={td}>
                    {s.probabilistic_sharpe == null ? "–" : formatPct(s.probabilistic_sharpe, 0)}
                  </td>
                  <td className={cn(td, "font-medium")}>
                    {s.deflated_sharpe == null ? "–" : formatPct(s.deflated_sharpe, 0)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <p className="-mt-2 text-xs text-muted-foreground">
        PSR: probability the true Sharpe is above 0 given the track record&apos;s length, skew and
        fat tails. DSR (deflated Sharpe): the same against the best Sharpe{" "}
        {st.trials ?? strat.length} skill-less strategies would show by luck, so trying many
        variants and keeping the best is charged for. Built with <code>marketsim.backtester</code>.
      </p>
      {doc.fitness && <FitnessPanel fitness={doc.fitness} />}
      <Panel title="Growth of $1" icon={Gauge} subtitle="Each strategy's equity after costs">
        <XYChart
          x={st.dates.map((_, i) => i)}
          series={strat.map(([k, s]) => ({
            key: k,
            label: s.label,
            values: s.equity,
            color: STRAT_COLOR[k] ?? "var(--muted-foreground)",
            width: k === "buy_hold" ? 2 : 1.5,
          }))}
          height={300}
          xFormat={(i) => st.dates[Math.round(i)] ?? ""}
          yFormat={(v) => `$${v.toFixed(2)}`}
          label="Equity of every strategy after costs"
        />
      </Panel>

      {strat.some(([, s]) => s.drawdown) && (
        <Panel
          title="Drawdowns"
          icon={Gauge}
          subtitle="Distance below each strategy's running peak"
        >
          <XYChart
            x={st.dates.map((_, i) => i)}
            series={strat.map(([k, s]) => ({
              key: k,
              label: s.label,
              values: (s.drawdown ?? []).map((v) => v * 100),
              color: STRAT_COLOR[k] ?? "var(--muted-foreground)",
            }))}
            height={220}
            zeroLine={0}
            xFormat={(i) => st.dates[Math.round(i)] ?? ""}
            yFormat={(v) => `${v.toFixed(0)}%`}
            label="Drawdown of every strategy"
          />
        </Panel>
      )}

      {Object.keys(doc.agent_params).length > 0 && (
        <Panel
          title="Fitted agent behaviour"
          icon={Sigma}
          subtitle="From marketsim.agent_fit: matched to AAPL's 2016–2023 statistical fingerprint"
        >
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
            {Object.entries(doc.agent_params).map(([k, v]) => (
              <div key={k}>
                <dt className="font-mono text-xs text-muted-foreground">{k}</dt>
                <dd className="tabular-nums">{v.toPrecision(3)}</dd>
              </div>
            ))}
          </dl>
        </Panel>
      )}
    </>
  );
}

export function StrategyPage() {
  const list = useExperiments();
  const [ticker, setTicker] = useState<string | null>(null);
  const chosen = ticker ?? list.data?.[0]?.ticker ?? null;
  const q = useStrategy(chosen);
  const doc = q.data;
  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-5 p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-mono text-[11px] tracking-[0.16em] text-primary">
            FORECASTS & STRATEGY
          </p>
          <h2 className="mt-1 text-2xl font-semibold tracking-tight">
            {doc
              ? `${doc.ticker} · expected prices and trading results`
              : "Expected prices and trading results"}
          </h2>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            The recalibrated agent model's forecast for every test day (mean, standard deviation,
            quantiles, P(up)), how those forecasts scored, and what trading on them would have
            earned.
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
      {list.isLoading || q.isLoading ? (
        <Skeleton className="h-72" />
      ) : !doc ? (
        <EmptyState
          icon={WalletCards}
          title="No strategy results yet"
          description="Run: uv run python -m marketsim.experiment AAPL (it writes strategy.json at the end)"
        />
      ) : (
        <Body doc={doc} />
      )}
    </div>
  );
}
