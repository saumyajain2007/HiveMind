import { Activity, Cpu, Gauge, LineChart, ListOrdered } from "lucide-react";

import { EmptyState } from "@/components/EmptyState";
import { XYChart } from "@/components/charts/XYChart";
import { Panel } from "@/components/Panel";
import { Stat } from "@/components/Stat";
import { Skeleton } from "@/components/ui/skeleton";
import { useAlgoRun, useExperiments } from "@/lib/api/queries";
import { formatPrice, formatSigned, formatSignedPct } from "@/lib/format";
import { cn } from "@/lib/utils";

const FEATURE_LABEL: Record<string, string> = {
  abm_mu: "agent model forecast",
  abm_sd: "agent model spread",
  oracle_mu: "event-replay forecast",
  event_true_ar: "event reaction estimate",
  earnings_next: "earnings calendar",
  ret_1d: "1-day momentum",
  ret_5d: "5-day momentum",
  ret_20d: "20-day momentum",
  trailing_vol: "trailing volatility",
};

const th = "py-2 text-right font-medium";
const td = "py-2 text-right tabular-nums";

export function AlgoPage() {
  const list = useExperiments();
  const ticker = list.data?.[0]?.ticker ?? null;
  const q = useAlgoRun(ticker);
  const d = q.data;

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-5 p-6">
      <div>
        <p className="font-mono text-[11px] tracking-[0.16em] text-primary">ALGO RUN</p>
        <h2 className="mt-1 flex items-center gap-2 text-2xl font-semibold tracking-tight">
          {d ? `${d.ticker} · event-driven agent strategy` : "Event-driven agent strategy"}
          <span className="rounded border px-1.5 py-0.5 font-mono text-[10px] font-normal tracking-wide text-muted-foreground">
            Illustrative
          </span>
        </h2>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          {d
            ? `Daily, ${d.period[0]} to ${d.period[1]}: the agent model's forecasts and event estimates combined into one signal, positioned at each close.`
            : "The agent model's forecasts and event estimates combined into one daily signal."}
        </p>
      </div>

      {list.isLoading || q.isLoading ? (
        <Skeleton className="h-72" />
      ) : !d ? (
        <EmptyState
          icon={Cpu}
          title="No run yet"
          description="Run: uv run python -m marketsim.leaked AAPL"
        />
      ) : (
        <Body d={d} />
      )}

      <p className="mt-6 border-t pt-3 text-[11px] text-muted-foreground">
        Hindsight-calibrated demonstration; methodology in the README.
      </p>
    </div>
  );
}

function Body({ d }: { d: NonNullable<ReturnType<typeof useAlgoRun>["data"]> }) {
  const s = d.stats;
  const n = (k: string) => (typeof s[k] === "number" ? (s[k] as number) : null);
  const x = d.dates.map((_, i) => i);
  const bhRet = (d.buy_hold_equity.at(-1) ?? 1) - 1;
  const recent = [...d.trades].reverse().slice(0, 15);
  const pct = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}%`;

  return (
    <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        <Stat
          label="Sharpe ratio"
          value={n("sharpe")}
          format={(v) => v.toFixed(2)}
          hint={`95% CI ${d.sharpe_ci95[0].toFixed(2)}–${d.sharpe_ci95[1].toFixed(2)}`}
        />
        <Stat
          label="Model fitness"
          value={d.fitness.ic_t}
          format={(v) => v.toFixed(2)}
          hint={`IC ${formatSigned(d.fitness.information_coefficient, 3)} (t-stat)`}
        />
        <Stat
          label="Total return"
          value={(n("total_return") ?? 0) * 100}
          format={pct}
          hint={`buy and hold ${formatSignedPct(bhRet, 1)}`}
        />
        <Stat
          label="Max drawdown"
          value={(n("max_drawdown") ?? 0) * 100}
          format={(v) => `${v.toFixed(1)}%`}
        />
        <Stat
          label="Win rate"
          value={(n("win_rate") ?? 0) * 100}
          format={(v) => `${v.toFixed(0)}%`}
          hint={`${n("n_trades") ?? 0} trades`}
        />
        <Stat
          label="Hit rate"
          value={d.fitness.hit_rate * 100}
          format={(v) => `${v.toFixed(0)}%`}
          hint="daily direction"
        />
      </div>

      <Panel
        title="Price and position"
        icon={LineChart}
        subtitle="Close price · shaded: days the strategy is short"
      >
        <XYChart
          x={x}
          series={[
            {
              key: "close",
              label: "Close",
              values: d.close,
              color: "var(--foreground)",
              width: 1.5,
            },
          ]}
          shades={d.positions.flatMap((p, i) => (p < 0 ? [{ x0: i - 0.5, x1: i + 0.5 }] : []))}
          height={280}
          legend={false}
          xFormat={(i) => d.dates[Math.round(i)] ?? ""}
          yFormat={(v) => formatPrice(v, 0)}
          label="Close price with the strategy's short days shaded"
        />
      </Panel>

      <Panel
        title="Growth of $1"
        icon={Activity}
        subtitle="After costs (1 bp commission + 4 bp slippage, short borrow)"
      >
        <XYChart
          x={x}
          series={[
            { key: "algo", label: "Strategy", values: d.equity, color: "var(--primary)", width: 2 },
            {
              key: "bh",
              label: "Buy and hold",
              values: d.buy_hold_equity,
              color: "var(--muted-foreground)",
            },
          ]}
          height={280}
          xFormat={(i) => d.dates[Math.round(i)] ?? ""}
          yFormat={(v) => `$${v.toFixed(2)}`}
          label="Equity of the strategy and of buy and hold"
        />
      </Panel>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Signal" icon={Cpu} subtitle="What drives the position">
          <ul className="flex flex-wrap gap-2 text-sm">
            {d.features.map((f) => (
              <li key={f} className="rounded-md border bg-surface-2/50 px-2 py-1">
                {FEATURE_LABEL[f] ?? f}
              </li>
            ))}
          </ul>
          <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Position rule</dt>
            <dd>
              {d.rule === "sign"
                ? "long / short on the signal's sign"
                : d.rule === "scaled"
                  ? "sized by signal strength (±2×)"
                  : "long / short beyond ±0.5 sd, else flat"}
            </dd>
            <dt className="text-muted-foreground">Sortino</dt>
            <dd className="tabular-nums">{n("sortino")?.toFixed(2) ?? "–"}</dd>
            <dt className="text-muted-foreground">Profit factor</dt>
            <dd className="tabular-nums">{n("profit_factor")?.toFixed(2) ?? "–"}</dd>
            <dt className="text-muted-foreground">Rank IC</dt>
            <dd className="tabular-nums">{formatSigned(d.fitness.rank_ic, 3)}</dd>
            <dt className="text-muted-foreground">Brier (climatology)</dt>
            <dd className="tabular-nums">
              {d.fitness.brier.toFixed(3)} ({d.fitness.brier_climatology.toFixed(3)})
            </dd>
          </dl>
        </Panel>
        <Panel title="Drawdown" icon={Gauge} subtitle="Below the running peak">
          <XYChart
            x={x}
            series={[
              {
                key: "dd",
                label: "Drawdown",
                values: d.drawdown.map((v) => v * 100),
                color: "var(--bear)",
              },
            ]}
            height={200}
            legend={false}
            zeroLine={0}
            xFormat={(i) => d.dates[Math.round(i)] ?? ""}
            yFormat={(v) => `${v.toFixed(0)}%`}
            label="Strategy drawdown"
          />
        </Panel>
      </div>

      <Panel
        title="Recent trades"
        icon={ListOrdered}
        subtitle="The latest 15 positions, newest first"
      >
        <div
          className="overflow-x-auto rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          tabIndex={0}
          role="region"
          aria-label="Recent trades table"
        >
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="py-2 font-medium">Side</th>
                <th className="py-2 font-medium">Entry</th>
                <th className="py-2 font-medium">Exit</th>
                <th className={th}>Days</th>
                <th className={th}>Size</th>
                <th className={th}>Return</th>
              </tr>
            </thead>
            <tbody>
              {recent.map((t) => (
                <tr key={`${t.entry}-${t.side}`} className="border-b last:border-0">
                  <td
                    className={cn(
                      "py-2 capitalize",
                      t.side === "long" ? "text-bull-text" : "text-bear-text",
                    )}
                  >
                    {t.side}
                  </td>
                  <td className="py-2 font-mono text-xs">{t.entry}</td>
                  <td className="py-2 font-mono text-xs">{t.exit}</td>
                  <td className={td}>{t.bars}</td>
                  <td className={td}>{t.weight.toFixed(2)}×</td>
                  <td className={cn(td, t.ret >= 0 ? "text-bull-text" : "text-bear-text")}>
                    {formatSignedPct(t.ret, 2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}
