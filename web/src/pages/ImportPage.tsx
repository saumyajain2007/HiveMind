import {
  Check,
  DownloadCloud,
  Loader2,
  MessagesSquare,
  Newspaper,
  ScanSearch,
  Search,
  TrendingUp,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { ScatterChart } from "@/components/charts/ScatterChart";
import { XYChart } from "@/components/charts/XYChart";
import { Panel } from "@/components/Panel";
import { Stat } from "@/components/Stat";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { ClassifiedEvent, StockImport } from "@/lib/api/experiments";
import { useStockImport, useStocks } from "@/lib/api/queries";
import { formatCompact, formatPrice, formatSignedPct } from "@/lib/format";
import { cn } from "@/lib/utils";

const STEPS = [
  { name: "Prices", provider: "Yahoo Finance" },
  { name: "Filings", provider: "SEC EDGAR" },
  { name: "Reddit", provider: "r/stocks, r/investing, r/wallstreetbets" },
  { name: "X", provider: "cashtag search" },
  { name: "StockTwits", provider: "symbol stream" },
  { name: "YouTube", provider: "titles and comments" },
  { name: "TikTok", provider: "hashtag search" },
];

const GROUP_LABEL: Record<string, string> = {
  earnings: "Earnings",
  periodic_report: "Periodic report",
  executive: "Management",
  other_event: "Other event",
  disclosure: "Disclosure",
  agreement: "Agreement",
  deal: "Deal",
  governance: "Governance",
  financing: "Financing",
  vote: "Shareholder vote",
};

const PLATFORM_COLOR: Record<string, string> = {
  Reddit: "var(--reddit)",
  X: "var(--twitter)",
  StockTwits: "var(--primary)",
  YouTube: "var(--youtube)",
  TikTok: "var(--tiktok)",
};

const scrollRegion =
  "overflow-y-auto rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring/60";

export function ImportPage() {
  const stocks = useStocks();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState("AAPL");
  const [importing, setImporting] = useState<string | null>(null);
  const [step, setStep] = useState(0);
  const q = useStockImport(importing);

  // walk through the sources while the import runs; finish once the data is in
  useEffect(() => {
    if (!importing) return;
    const id = window.setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length)), 380);
    return () => window.clearInterval(id);
  }, [importing]);

  const done = Boolean(q.data) && step >= STEPS.length;
  const list = useMemo(() => {
    const t = query.trim().toLowerCase();
    return (stocks.data ?? []).filter(
      (s) => !t || s.ticker.toLowerCase().includes(t) || s.name.toLowerCase().includes(t),
    );
  }, [stocks.data, query]);

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-5 p-6">
      <div>
        <p className="font-mono text-[11px] tracking-[0.16em] text-primary">STOCK IMPORT</p>
        <h2 className="mt-1 text-2xl font-semibold tracking-tight">Import a stock</h2>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Pick a listed company to pull two years of prices, its regulatory filings and what people
          are saying about it, then see how the event classifier reads its news.
        </p>
      </div>

      <Panel
        title="Choose a stock"
        icon={Search}
        subtitle={`${stocks.data?.length ?? "…"} US large caps`}
        actions={
          <Button
            onClick={() => {
              setStep(0);
              setImporting(selected);
            }}
            disabled={!selected || (importing === selected && !done)}
          >
            {importing === selected && !done ? (
              <Loader2 className="animate-spin" />
            ) : (
              <DownloadCloud />
            )}
            Import {selected}
          </Button>
        }
      >
        <label className="sr-only" htmlFor="stock-search">
          Search stocks
        </label>
        <input
          id="stock-search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by ticker or name"
          className="mb-3 w-full rounded-md border bg-surface-2/40 px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/60 md:w-80"
        />
        {stocks.isLoading ? (
          <Skeleton className="h-40" />
        ) : (
          <div
            className={cn(scrollRegion, "max-h-56")}
            tabIndex={0}
            role="region"
            aria-label="Stock list"
          >
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
              {list.map((s) => (
                <button
                  key={s.ticker}
                  type="button"
                  aria-pressed={selected === s.ticker}
                  onClick={() => setSelected(s.ticker)}
                  className={cn(
                    "rounded-md border px-3 py-2 text-left transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
                    selected === s.ticker
                      ? "border-primary bg-primary/10"
                      : "bg-surface-2/40 hover:bg-surface-2",
                  )}
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-mono text-sm font-semibold">{s.ticker}</span>
                    <span className="font-mono text-xs text-muted-foreground tabular-nums">
                      {formatPrice(s.last_close)}
                    </span>
                  </div>
                  <div className="truncate text-xs text-muted-foreground">{s.name}</div>
                </button>
              ))}
            </div>
          </div>
        )}
      </Panel>

      {importing && (
        <Panel title={`Importing ${importing}`} icon={DownloadCloud} subtitle="Sources">
          <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((s, i) => {
              const finished = i < step && (q.data || i < STEPS.length - 1);
              const count = q.data?.sources.find((x) => x.name === s.name)?.count;
              return (
                <li
                  key={s.name}
                  className="flex items-center gap-3 rounded-md border bg-surface-2/40 px-3 py-2"
                >
                  <span
                    className={cn(
                      "grid size-6 place-items-center rounded-full border",
                      finished ? "border-bull bg-bull/15 text-bull-text" : "text-muted-foreground",
                    )}
                  >
                    {finished ? (
                      <Check className="size-3.5" />
                    ) : i === step ? (
                      <Loader2 className="size-3.5 animate-spin" />
                    ) : null}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium">{s.name}</div>
                    <div className="truncate text-xs text-muted-foreground">{s.provider}</div>
                  </div>
                  <span className="font-mono text-xs text-muted-foreground tabular-nums">
                    {finished && count != null ? formatCompact(count) : ""}
                  </span>
                </li>
              );
            })}
          </ol>
        </Panel>
      )}

      {!importing ? (
        <EmptyState
          icon={DownloadCloud}
          title="Nothing imported yet"
          description="Choose a stock and press Import."
        />
      ) : q.isError ? (
        <EmptyState icon={DownloadCloud} title="Import failed" description={String(q.error)} />
      ) : !done || !q.data ? (
        <Skeleton className="h-72" />
      ) : (
        <Imported d={q.data} />
      )}
    </div>
  );
}

function Imported({ d }: { d: StockImport }) {
  const x = d.dates.map((_, i) => i);
  const ret = (d.close.at(-1) ?? 0) / (d.close[0] ?? 1) - 1;
  const m = d.classification.metrics;
  const earnings = d.headlines.filter((h) => h.group === "earnings");
  const [platform, setPlatform] = useState<string>("All");
  const posts = d.social.posts.filter((p) => platform === "All" || p.platform === platform);
  const weekly = (v: number[]) => v.map((_, i) => mean(v.slice(Math.max(0, i - 4), i + 1)));

  return (
    <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Last close" value={d.close.at(-1)} format={(v) => formatPrice(v)} />
        <Stat
          label="Two-year return"
          value={ret * 100}
          format={(v) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}%`}
          hint={`${d.period[0]} to ${d.period[1]}`}
        />
        <Stat label="Filings" value={d.headlines.length} hint={`${earnings.length} earnings`} />
        <Stat label="Social posts" value={d.social.n_posts} hint="5 platforms" />
        <Stat
          label="Classifier accuracy"
          value={(m.accuracy ?? 0) * 100}
          format={(v) => `${v.toFixed(0)}%`}
          hint={`${m.n ?? 0} events since ${d.classification.split}`}
        />
      </div>

      <Panel title={`${d.name} (${d.ticker})`} icon={TrendingUp} subtitle="Close · lines: earnings">
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
          markers={earnings.map((h) => ({
            x: h.index,
            label: h.headline,
            color: "var(--primary)",
            tag: "E",
          }))}
          height={280}
          legend={false}
          xFormat={(i) => d.dates[Math.round(i)] ?? ""}
          yFormat={(v) => formatPrice(v, 0)}
          label={`${d.ticker} close price with earnings releases marked`}
        />
      </Panel>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel
          title="Mentions"
          icon={MessagesSquare}
          subtitle="Posts per day by platform, 5-day mean"
        >
          <XYChart
            x={x}
            series={d.social.platforms.map((p) => ({
              key: p,
              label: p,
              values: weekly(d.social.by_platform[p] ?? []),
              color: PLATFORM_COLOR[p] ?? "var(--muted-foreground)",
            }))}
            height={220}
            xFormat={(i) => d.dates[Math.round(i)] ?? ""}
            yFormat={(v) => formatCompact(v)}
            label="Daily mentions by platform"
          />
        </Panel>
        <Panel
          title="Sentiment"
          icon={MessagesSquare}
          subtitle="Net tone of posts, −1 to +1, 5-day mean"
        >
          <XYChart
            x={x}
            series={[
              {
                key: "sent",
                label: "Sentiment",
                values: weekly(d.social.sentiment),
                color: "var(--primary)",
              },
            ]}
            height={220}
            legend={false}
            zeroLine={0}
            xFormat={(i) => d.dates[Math.round(i)] ?? ""}
            yFormat={(v) => v.toFixed(2)}
            label="Social sentiment"
          />
        </Panel>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel
          title="Headlines"
          icon={Newspaper}
          subtitle="Filings, newest first, with the day's abnormal return"
        >
          <div
            className={cn(scrollRegion, "max-h-96")}
            tabIndex={0}
            role="region"
            aria-label="Headline list"
          >
            <ul className="divide-y">
              {d.headlines.map((h) => (
                <li key={`${h.released}-${h.headline}`} className="flex gap-3 py-2 text-sm">
                  <span className="w-20 shrink-0 font-mono text-xs text-muted-foreground">
                    {h.date}
                  </span>
                  <div className="min-w-0 flex-1">
                    {h.url ? (
                      <a
                        href={h.url}
                        target="_blank"
                        rel="noreferrer"
                        className="hover:underline focus-visible:underline focus-visible:outline-none"
                      >
                        {h.headline}
                      </a>
                    ) : (
                      h.headline
                    )}
                    <div className="text-xs text-muted-foreground">
                      {h.source} · {GROUP_LABEL[h.group] ?? h.group}
                    </div>
                  </div>
                  <span
                    className={cn(
                      "shrink-0 font-mono text-xs tabular-nums",
                      h.abnormal_return == null
                        ? "text-muted-foreground"
                        : h.abnormal_return >= 0
                          ? "text-bull-text"
                          : "text-bear-text",
                    )}
                  >
                    {h.abnormal_return == null ? "–" : formatSignedPct(h.abnormal_return, 1)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </Panel>
        <Panel
          title="Social feed"
          icon={MessagesSquare}
          subtitle="Most-discussed days"
          actions={
            <div className="flex flex-wrap gap-1" role="group" aria-label="Platform">
              {["All", ...d.social.platforms].map((p) => (
                <button
                  key={p}
                  type="button"
                  aria-pressed={platform === p}
                  onClick={() => setPlatform(p)}
                  className={cn(
                    "rounded px-2 py-0.5 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
                    platform === p ? "bg-primary/15 text-foreground" : "text-muted-foreground",
                  )}
                >
                  {p}
                </button>
              ))}
            </div>
          }
        >
          <div
            className={cn(scrollRegion, "max-h-96")}
            tabIndex={0}
            role="region"
            aria-label="Social posts"
          >
            <ul className="divide-y">
              {posts.map((p, i) => (
                <li key={`${p.date}-${i}`} className="py-2 text-sm">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">{p.handle}</span>
                    <span>{p.platform}</span>
                    <span className="font-mono">{p.date}</span>
                    <span className="ml-auto tabular-nums">♥ {formatCompact(p.likes)}</span>
                  </div>
                  <p className="mt-0.5">{p.text}</p>
                </li>
              ))}
            </ul>
          </div>
        </Panel>
      </div>

      <Classifier d={d} />
    </>
  );
}

function Classifier({ d }: { d: StockImport }) {
  const c = d.classification;
  const m = c.metrics;
  const events = [...c.events].reverse();
  const pct = (v: number | null | undefined) => (v == null ? null : v * 100);
  return (
    <Panel
      title="Event classification"
      icon={ScanSearch}
      subtitle={`Pooled classifier trained on 50 stocks' filings before ${c.split}; ${d.ticker}'s events since then`}
    >
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label="Accuracy (down / flat / up)"
          value={pct(m.accuracy)}
          format={(v) => `${v.toFixed(0)}%`}
          hint={`always the commonest: ${((m.majority_accuracy ?? 0) * 100).toFixed(0)}%`}
        />
        <Stat
          label="Direction hit rate"
          value={pct(m.direction_hit_rate)}
          format={(v) => `${v.toFixed(0)}%`}
          hint="events that moved the stock"
        />
        <Stat
          label="Size correlation"
          value={m.size_corr ?? null}
          format={(v) => v.toFixed(2)}
          hint="predicted vs actual |move| (log)"
        />
        <Stat
          label="Size error"
          value={(m.size_mae ?? 0) * 100}
          format={(v) => `${v.toFixed(2)} pp`}
          hint={`average move ${((m.mean_abs_ar ?? 0) * 100).toFixed(2)}%`}
        />
      </div>
      <div className="mt-5 grid gap-5 lg:grid-cols-[2fr_1fr]">
        <div
          className="overflow-x-auto rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          tabIndex={0}
          role="region"
          aria-label="Classified events"
        >
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="py-2 font-medium">Date</th>
                <th className="py-2 font-medium">Event</th>
                <th className="py-2 font-medium">P(down / flat / up)</th>
                <th className="py-2 font-medium">Predicted</th>
                <th className="py-2 font-medium">Actual</th>
                <th className="py-2 text-right font-medium">Move</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <Row key={`${e.date}-${e.form}-${e.group}`} e={e} />
              ))}
            </tbody>
          </table>
        </div>
        <ScatterChart
          points={c.events.map((e) => ({
            x: e.predicted_size * 100,
            y: Math.abs(e.actual_ar) * 100,
            label: `${e.date} ${GROUP_LABEL[e.group] ?? e.group}`,
            highlight: e.group === "earnings",
          }))}
          height={300}
          xLabel="Predicted size (%)"
          yLabel="Actual |move| (%)"
          xFormat={(v) => v.toFixed(1)}
          yFormat={(v) => v.toFixed(1)}
          label="Predicted against actual size of each event's move"
          color="var(--primary)"
        />
      </div>
    </Panel>
  );
}

function Row({ e }: { e: ClassifiedEvent }) {
  const hit = e.predicted === e.actual;
  const tone = (c: string) =>
    c === "up" ? "text-bull-text" : c === "down" ? "text-bear-text" : "text-muted-foreground";
  return (
    <tr className="border-b last:border-0">
      <td className="py-2 font-mono text-xs">{e.date}</td>
      <td className="py-2">
        {GROUP_LABEL[e.group] ?? e.group}
        <span className="ml-1 text-xs text-muted-foreground">{e.form}</span>
      </td>
      <td className="py-2">
        <div className="flex h-2 w-32 overflow-hidden rounded-sm" aria-hidden="true">
          <span className="bg-bear" style={{ width: `${e.proba[0] * 100}%` }} />
          <span className="bg-muted-foreground/40" style={{ width: `${e.proba[1] * 100}%` }} />
          <span className="bg-bull" style={{ width: `${e.proba[2] * 100}%` }} />
        </div>
        <span className="sr-only">{e.proba.map((p) => `${Math.round(p * 100)}%`).join(" / ")}</span>
      </td>
      <td className={cn("py-2 capitalize", tone(e.predicted))}>{e.predicted}</td>
      <td className={cn("py-2 capitalize", tone(e.actual))}>
        {e.actual}
        <span className={cn("ml-1 text-xs", hit ? "text-bull-text" : "text-muted-foreground")}>
          {hit ? "✓" : "✗"}
        </span>
      </td>
      <td
        className={cn(
          "py-2 text-right font-mono text-xs tabular-nums",
          e.actual_ar >= 0 ? "text-bull-text" : "text-bear-text",
        )}
      >
        {formatSignedPct(e.actual_ar, 1)}
      </td>
    </tr>
  );
}

function mean(v: number[]): number {
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : 0;
}
