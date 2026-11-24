import {
  BarChart3,
  ChartSpline,
  Download,
  FileImage,
  ListTree,
  Play,
  Sigma,
  Waves,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { Link } from "react-router";

import { Tag } from "@/components/badges";
import { BarChart } from "@/components/charts/BarChart";
import type { Marker } from "@/components/charts/XYChart";
import { XYChart } from "@/components/charts/XYChart";
import { EmptyState } from "@/components/EmptyState";
import { Panel } from "@/components/Panel";
import { Stat } from "@/components/Stat";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { histogram, kde, lognormalPdf, quantile } from "@/features/montecarlo/stats";
import { useMonteCarloProgress } from "@/features/montecarlo/useProgress";
import { RunPicker } from "@/features/runs/RunPicker";
import { useSelectedRun } from "@/features/runs/useSelectedRun";
import { usePaths, useQuantiles, useRun, useSeries, useStylized } from "@/lib/api/queries";
import type { QuantilesResponse } from "@/lib/api/results";
import { downloadCsv, exportPng, exportSvg } from "@/lib/exportChart";
import { formatPct, formatPrice, formatSignedPct, simClock, TICKS_PER_DAY } from "@/lib/format";
import { cn } from "@/lib/utils";

const QS = ["0.05", "0.25", "0.5", "0.75", "0.95"] as const;

function ExportButtons({
  target,
  name,
  csv,
}: {
  target: React.RefObject<HTMLDivElement | null>;
  name: string;
  csv?: () => void;
}) {
  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => exportPng(target.current, `${name}.png`)}
        aria-label={`Export ${name} as PNG`}
      >
        <FileImage />
        PNG
      </Button>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => exportSvg(target.current, `${name}.svg`)}
        aria-label={`Export ${name} as SVG`}
      >
        SVG
      </Button>
      {csv && (
        <Button variant="ghost" size="sm" onClick={csv} aria-label={`Export ${name} as CSV`}>
          <Download />
          CSV
        </Button>
      )}
    </>
  );
}

export function MonteCarloPage() {
  const sel = useSelectedRun(["montecarlo"]);
  const run = useRun(sel.id);
  const running = run.data?.status === "running" || run.data?.status === "queued";
  const done = run.data?.status === "done" || run.data?.status === "cancelled";
  const progress = useMonteCarloProgress(sel.id, running);
  const q = useQuantiles(done ? sel.id : null);
  const samples = usePaths(done ? sel.id : null, 20, 2);
  const terminal = usePaths(done ? sel.id : null, 1000, TICKS_PER_DAY);
  const rep = useSeries(done ? sel.id : null, 2);
  const sf = useStylized(done ? sel.id : null);
  const [tab, setTab] = useState<"fan" | "dist" | "facts">("fan");
  const [showPaths, setShowPaths] = useState(false);
  const fanRef = useRef<HTMLDivElement>(null);
  const distRef = useRef<HTMLDivElement>(null);

  const bands: QuantilesResponse["quantiles"] | null =
    q.data?.quantiles ??
    (progress?.quantiles as QuantilesResponse["quantiles"] | undefined) ??
    null;
  const n = bands?.["0.5"]?.length ?? 0;
  const fan = useMemo(() => {
    if (!bands || !n) return null;
    const step = Math.max(1, Math.ceil(n / 500));
    const idx = Array.from({ length: Math.ceil(n / step) }, (_, i) => i * step);
    if (idx[idx.length - 1] !== n - 1) idx.push(n - 1);
    const pick = (a: number[]) => idx.map((i) => a[i]!);
    const markers: Marker[] = (rep.data?.events ?? [])
      .filter((e) => e.kind !== "price_move")
      .map((e) => ({
        x: e.injected,
        label: `${e.label ?? e.kind} · ${simClock(e.injected).label}`,
        color: e.kind === "rumour" || e.kind === "leak" ? "var(--narrative)" : "var(--official)",
      }));
    const pathTicks =
      samples.data?.tick ?? samples.data?.paths[0]?.map((_, i) => i * (samples.data?.every ?? 1));
    return {
      x: idx,
      q: Object.fromEntries(QS.map((k) => [k, pick(bands[k])])) as Record<
        (typeof QS)[number],
        number[]
      >,
      vTrue: q.data ? pick(q.data.v_true) : null,
      markers,
      paths:
        showPaths && samples.data && pathTicks
          ? samples.data.paths.map((p, j) => {
              const at = new Map(pathTicks.map((t, i) => [t, p[i]!]));
              return {
                key: `path-${j}`,
                label: `seed ${samples.data!.seeds[j]}`,
                values: idx.map((t) => at.get(t) ?? null),
                color: "var(--foreground)",
                ghost: true,
              };
            })
          : [],
    };
  }, [bands, n, q.data, rep.data, samples.data, showPaths]);

  const dist = useMemo(() => {
    const finals = terminal.data?.paths.map((p) => p[p.length - 1]!).filter(Number.isFinite) ?? [];
    if (finals.length < 2 || !q.data) return null;
    const sorted = [...finals].sort((a, b) => a - b);
    const p0 = q.data.summary.initial_price;
    const days = q.data.n_ticks / TICKS_PER_DAY;
    const iv = (rep.data?.series.iv[0] ?? 0.3) / Math.sqrt(252);
    const s = iv * Math.sqrt(days);
    const lo = Math.min(sorted[0]!, p0 * Math.exp(-3 * s));
    const hi = Math.max(sorted[sorted.length - 1]!, p0 * Math.exp(3 * s));
    const bins = histogram(
      finals,
      lo,
      hi,
      Math.min(40, Math.max(10, Math.round(Math.sqrt(finals.length) * 2))),
    );
    const xs = Array.from({ length: 160 }, (_, i) => lo + ((hi - lo) * i) / 159);
    return {
      bins,
      xs,
      kde: kde(finals, xs),
      rw: xs.map((x) => lognormalPdf(x, p0, s)),
      n: finals.length,
      median: quantile(sorted, 0.5),
      p0,
    };
  }, [terminal.data, q.data, rep.data]);

  const summary = q.data?.summary;
  if (!sel.loading && !sel.candidates.length) {
    return (
      <div className="grid min-h-full place-items-center p-6">
        <EmptyState
          icon={ChartSpline}
          title="No Monte Carlo run yet"
          description="Build a scenario and press “Monte Carlo ×R” to see the distribution of price paths."
          actions={
            <Button asChild>
              <Link to="/builder">
                <Play />
                Open the Builder
              </Link>
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-[1500px] flex-col gap-5 p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-mono text-[11px] tracking-[0.16em] text-primary">MONTE CARLO</p>
          <h2 className="mt-1 text-2xl font-semibold tracking-tight">{run.data?.name ?? "…"}</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {run.data
              ? `${run.data.runs} runs · ${run.data.n_agents.toLocaleString()} agents · ${run.data.days} days · one world, seeds ${run.data.seed + 1}–${run.data.seed + run.data.runs}`
              : ""}
          </p>
        </div>
        <RunPicker value={sel.id} candidates={sel.candidates} onChange={sel.select} />
      </div>

      {running && (
        <div
          className="flex items-center gap-3 rounded-lg border bg-card px-4 py-2.5 text-sm"
          role="status"
        >
          <span className="relative flex size-2.5">
            <span className="absolute inline-flex size-full rounded-full bg-primary opacity-60 motion-safe:animate-ping" />
            <span className="relative inline-flex size-2.5 rounded-full bg-primary" />
          </span>
          Running:{" "}
          {progress
            ? `${progress.done} of ${progress.total} runs finished`
            : "waiting for the first run"}
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary transition-[width]"
              style={{ width: `${progress ? (100 * progress.done) / progress.total : 2}%` }}
            />
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <Stat
          label="Median final price"
          value={summary?.final_price_quantiles["0.5"]}
          format={(v) => formatPrice(v)}
          hint={summary ? `start ${formatPrice(summary.initial_price)}` : undefined}
        />
        <Stat
          label={`P(price < start) on day ${summary ? Math.round(summary.days) : 5}`}
          value={summary?.p_below_start}
          format={(v) => formatPct(v, 0)}
          hint="share of runs"
        />
        <Stat
          label="VaR 95%"
          value={summary?.var_95}
          format={(v) => formatPct(v)}
          hint="5th-percentile loss"
        />
        <Stat
          label="Median max drawdown"
          value={summary?.median_max_drawdown}
          format={(v) => formatPct(v)}
          hint="peak to trough"
        />
        <Stat label="Mean CRPS" value={null} hint="link a backtest in Analysis" />
      </div>

      <div
        className="flex gap-1 rounded-lg border bg-card p-1"
        role="tablist"
        aria-label="Monte Carlo views"
      >
        {(
          [
            ["fan", "Fan chart", ChartSpline],
            ["dist", "Terminal price", BarChart3],
            ["facts", "Stylised facts", Sigma],
          ] as const
        ).map(([k, label, Icon]) => (
          <button
            key={k}
            role="tab"
            type="button"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={cn(
              "inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
              tab === k
                ? "bg-primary/12 font-medium text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="size-4" aria-hidden />
            {label}
          </button>
        ))}
      </div>

      {tab === "fan" && (
        <Panel
          title="Price paths"
          subtitle="Bands: 5–95% and 25–75% of runs · line: median · dashed: hidden fundamental value"
          icon={ChartSpline}
          actions={
            <>
              <Button
                variant={showPaths ? "secondary" : "ghost"}
                size="sm"
                onClick={() => setShowPaths((s) => !s)}
                aria-pressed={showPaths}
              >
                <ListTree />
                20 sample paths
              </Button>
              <ExportButtons
                target={fanRef}
                name="fan-chart"
                csv={() =>
                  bands &&
                  downloadCsv(
                    ["tick", ...QS.map((k) => `q${k}`)],
                    bands["0.5"].map((_, i) => [i, ...QS.map((k) => bands[k][i]!.toFixed(4))]),
                    "quantiles.csv",
                  )
                }
              />
            </>
          }
        >
          <div ref={fanRef}>
            {fan ? (
              <XYChart
                x={fan.x}
                height={400}
                bands={[
                  {
                    key: "outer",
                    label: "5–95% of runs",
                    lo: fan.q["0.05"],
                    hi: fan.q["0.95"],
                    color: "var(--bull)",
                    opacity: 0.14,
                  },
                  {
                    key: "inner",
                    label: "25–75% of runs",
                    lo: fan.q["0.25"],
                    hi: fan.q["0.75"],
                    color: "var(--bull)",
                    opacity: 0.28,
                  },
                ]}
                series={[
                  ...fan.paths,
                  { key: "median", label: "Median", values: fan.q["0.5"], color: "var(--bull)" },
                  ...(fan.vTrue
                    ? [
                        {
                          key: "vtrue",
                          label: "Fundamental value (hidden)",
                          values: fan.vTrue,
                          color: "var(--fundamental)",
                          dash: "6 4",
                        },
                      ]
                    : []),
                ]}
                markers={fan.markers}
                xFormat={(t) => simClock(t).label}
                xTicks={Array.from(
                  { length: Math.ceil(n / TICKS_PER_DAY) },
                  (_, d) => d * TICKS_PER_DAY,
                )}
                yFormat={(v) => formatPrice(v)}
                label={`Fan chart of ${q.data?.n_runs ?? progress?.done ?? 0} simulated price paths`}
              />
            ) : (
              <Skeleton className="h-[400px]" />
            )}
          </div>
          {!q.data && progress && (
            <p className="mt-2 text-xs text-muted-foreground">
              Partial: {progress.done} runs so far. The bands fill in as runs finish.
            </p>
          )}
        </Panel>
      )}

      {tab === "dist" && (
        <Panel
          title="Terminal price"
          subtitle={
            dist
              ? `Final price of ${dist.n} runs vs a driftless random walk with the same implied vol`
              : "Final price of each run"
          }
          icon={BarChart3}
          actions={<ExportButtons target={distRef} name="terminal-price" />}
        >
          <div ref={distRef}>
            {dist ? (
              <XYChart
                x={dist.xs}
                height={360}
                series={[
                  {
                    key: "kde",
                    label: "Model (kernel density)",
                    values: dist.kde,
                    color: "var(--bull)",
                  },
                  {
                    key: "rw",
                    label: "Random walk benchmark",
                    values: dist.rw,
                    color: "var(--muted-foreground)",
                    dash: "6 4",
                  },
                ]}
                markers={[
                  { x: dist.p0, label: `Start ${formatPrice(dist.p0)}`, color: "var(--axis)" },
                ]}
                yDomain={[
                  0,
                  Math.max(...dist.bins.map((b) => b.density), ...dist.kde, ...dist.rw) * 1.1,
                ]}
                xFormat={(v) => formatPrice(v)}
                yFormat={(v) => v.toFixed(3)}
                label="Distribution of the final price"
                overlay={(sx, sy) =>
                  dist.bins.map((b, i) => (
                    <rect
                      key={i}
                      x={sx(b.x0) + 1}
                      width={Math.max(0, sx(b.x1) - sx(b.x0) - 2)}
                      y={sy(b.density)}
                      height={Math.max(0, sy(0) - sy(b.density))}
                      rx={2}
                      fill="var(--bull)"
                      opacity={0.25}
                    />
                  ))
                }
              />
            ) : (
              <Skeleton className="h-[360px]" />
            )}
          </div>
          {summary && (
            <div className="mt-3 flex flex-wrap gap-2">
              {QS.map((k) => (
                <Tag key={k}>
                  {Math.round(Number(k) * 100)}%: {formatPrice(summary.final_price_quantiles[k])}
                </Tag>
              ))}
              <Tag>mean log return {formatSignedPct(Math.expm1(summary.mean_log_return))}</Tag>
            </div>
          )}
        </Panel>
      )}

      {tab === "facts" && (
        <div className="grid gap-5 lg:grid-cols-2">
          <Panel
            title="Return distribution"
            subtitle="Open-tick returns in sd units vs the normal"
            icon={BarChart3}
            actions={
              sf.data?.excess_kurtosis != null && (
                <Tag>excess kurtosis {sf.data.excess_kurtosis.toFixed(2)}</Tag>
              )
            }
          >
            {sf.data ? (
              <XYChart
                x={sf.data.histogram.centres}
                height={280}
                series={[
                  {
                    key: "emp",
                    label: "Simulated",
                    values: sf.data.histogram.density,
                    color: "var(--bull)",
                    area: true,
                  },
                  {
                    key: "normal",
                    label: "Normal",
                    values: sf.data.histogram.normal,
                    color: "var(--muted-foreground)",
                    dash: "6 4",
                  },
                ]}
                yDomain={[
                  0,
                  Math.max(...sf.data.histogram.density, ...sf.data.histogram.normal) * 1.1,
                ]}
                xFormat={(v) => `${v.toFixed(0)}σ`}
                yFormat={(v) => v.toFixed(2)}
                label="Return distribution against the normal"
              />
            ) : (
              <Skeleton className="h-[280px]" />
            )}
          </Panel>
          <Panel
            title="Autocorrelation"
            subtitle="Of returns (r) and absolute returns (|r|), lags 1–10 · shaded: 95% band"
            icon={Waves}
          >
            {sf.data ? (
              <BarChart
                categories={sf.data.acf_r.map((_, i) => String(i + 1))}
                groups={[
                  {
                    key: "r",
                    label: "r",
                    color: "var(--fundamental)",
                    values: sf.data.acf_r.map((v) => v ?? 0),
                  },
                  {
                    key: "abs",
                    label: "|r|",
                    color: "var(--official)",
                    values: sf.data.acf_abs_r.map((v) => v ?? 0),
                  },
                ]}
                band={sf.data.band}
                height={280}
                yFormat={(v) => v.toFixed(2)}
                label="Autocorrelation of returns and absolute returns"
              />
            ) : (
              <Skeleton className="h-[280px]" />
            )}
          </Panel>
          <Panel
            title="Volatility clustering"
            subtitle="|return| per open tick, representative run"
            icon={Sigma}
            className="lg:col-span-2"
          >
            {rep.data ? (
              <VolStrip price={rep.data.series.price} ticks={rep.data.tick} />
            ) : (
              <Skeleton className="h-28" />
            )}
          </Panel>
        </div>
      )}
    </div>
  );
}

function VolStrip({ price, ticks }: { price: number[]; ticks: number[] }) {
  // open ticks only, laid end to end (no overnight gaps); one stem per tick
  const rows = useMemo(() => {
    const out: { t: number; r: number }[] = [];
    for (let i = 1; i < price.length; i++) {
      const d = ticks[i]! % TICKS_PER_DAY;
      if (d >= 38 && d < 64)
        out.push({ t: ticks[i]!, r: Math.abs(Math.log(price[i]! / price[i - 1]!)) * 100 });
    }
    return out;
  }, [price, ticks]);
  const x = rows.map((_, i) => i);
  const top = Math.max(0.01, ...rows.map((r) => r.r)) * 1.1;
  const dayStarts = rows.flatMap((r, i) =>
    i === 0 || simClock(r.t).day !== simClock(rows[i - 1]!.t).day ? [i] : [],
  );
  return (
    <XYChart
      x={x}
      height={150}
      series={[
        { key: "absr", label: "|r|", values: rows.map((r) => r.r), color: "transparent", width: 0 },
      ]}
      yDomain={[0, top]}
      xFormat={(i) => simClock(rows[Math.round(i)]?.t ?? 0).label}
      xTicks={dayStarts}
      yFormat={(v) => `${v.toFixed(1)}%`}
      label="Absolute open-tick returns over the run (market hours only)"
      legend={false}
      overlay={(sx, sy) =>
        rows.map((r, i) => (
          <line
            key={i}
            x1={sx(i)}
            x2={sx(i)}
            y1={sy(0)}
            y2={sy(r.r)}
            stroke="var(--official)"
            strokeWidth={2}
            strokeLinecap="round"
          />
        ))
      }
    />
  );
}
