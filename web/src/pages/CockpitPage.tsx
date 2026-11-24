import {
  Activity,
  CandlestickChart,
  Gauge,
  LineChart,
  Newspaper,
  Pause,
  Play,
  Radio,
  RotateCcw,
  Square,
  Users,
  XCircle,
} from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { useDemoReplay } from "@/app/useDemoReplay";
import { Tag } from "@/components/badges";
import { CATEGORICAL } from "@/components/charts/scale";
import { XYChart } from "@/components/charts/XYChart";
import { EmptyState } from "@/components/EmptyState";
import { Panel } from "@/components/Panel";
import { Sparkline } from "@/components/Sparkline";
import { Stat } from "@/components/Stat";
import { Button } from "@/components/ui/button";
import { ResizableGroup, ResizableHandle, ResizablePanel } from "@/components/ui/resizable";
import { NewsFeed } from "@/features/cockpit/NewsFeed";
import { PriceChart } from "@/features/cockpit/PriceChart";
import { ConfidenceGauge, ImbalanceMeter } from "@/features/cockpit/widgets";
import type { Schemas } from "@/lib/api/client";
import { useCancelRun, useCreateRun, useRun } from "@/lib/api/queries";
import {
  formatCompact,
  formatPct,
  formatPrice,
  formatSigned,
  simClock,
  TICKS_PER_DAY,
} from "@/lib/format";
import {
  awarenessHistory,
  born,
  connectRun,
  disconnectRun,
  framesPerSecond,
  series,
  useLive,
  useLiveVersion,
} from "@/lib/live/store";
import { useMotionTransition } from "@/lib/motion";
import { cn } from "@/lib/utils";

export function CockpitPage() {
  const status = useLive((s) => s.status);
  const demo = useDemoReplay();
  if (status === "idle") {
    return (
      <div className="grid min-h-full place-items-center p-6">
        <EmptyState
          icon={Activity}
          title="No live run"
          description="Start a run to watch the price, beliefs and news move tick by tick: candles with event markers, the news feed as items are born and spread, and playback controls."
          actions={
            <Button onClick={() => void demo.start()} disabled={demo.pending}>
              <Play />
              Run demo scenario
            </Button>
          }
        />
      </div>
    );
  }
  return <LiveCockpit />;
}

function ClockBadge({ tick }: { tick: number }) {
  const c = simClock(tick);
  return (
    <div
      className="flex items-center gap-2 rounded-lg border bg-surface-2 px-3 py-1.5"
      aria-live="off"
    >
      <span className="tabular font-mono text-lg font-semibold tracking-tight">{c.label}</span>
      <span
        className={cn(
          "rounded-full px-2 py-0.5 text-[11px] font-semibold",
          c.open
            ? "border border-status-good/50 text-status-good-text"
            : "border text-muted-foreground",
        )}
      >
        {c.open ? "Market open" : "Market closed"}
      </span>
    </div>
  );
}

function LiveCockpit() {
  const version = useLiveVersion();
  const meta = useLive((s) => s.meta);
  const status = useLive((s) => s.status);
  const runId = useLive((s) => s.runId);
  const summary = useLive((s) => s.summary);
  const run = useRun(runId);
  const cancel = useCancelRun();
  const create = useCreateRun();
  const [mode, setMode] = useState<"candles" | "line">("candles");
  const [cursor, setCursor] = useState<number | null>(null); // null = follow live
  const [fps, setFps] = useState(0);
  const progressTransition = useMotionTransition({ duration: 0.3 });

  useEffect(() => {
    const id = window.setInterval(() => setFps(framesPerSecond()), 500);
    return () => window.clearInterval(id);
  }, []);

  const data = useMemo(() => {
    void version; // re-read the ring buffers whenever new frames were flushed
    const ticks = series.tick.toArray();
    const n = ticks.length;
    const end = cursor == null ? n : Math.min(n, cursor + 1);
    const cut = <T,>(a: T[]) => (end === n ? a : a.slice(0, end));
    const tick = ticks[end - 1] ?? 0;
    const items = born.filter((b) => b.tick <= tick);
    // awareness at the cursor, per item
    const awareness: Record<string, number> = {};
    for (const [id, h] of awarenessHistory) {
      let lo = 0;
      let hi = h.ticks.length - 1;
      if (hi < 0 || h.ticks[0]! > tick) continue;
      while (lo < hi) {
        const mid = (lo + hi + 1) >> 1;
        if (h.ticks[mid]! <= tick) lo = mid;
        else hi = mid - 1;
      }
      awareness[String(id)] = h.counts[lo]!;
    }
    const conf = cut(series.confidence.toArray());
    const vol = cut(series.volume.toArray());
    return {
      n,
      end,
      tick,
      ticks: cut(ticks),
      price: cut(series.price.toArray()),
      vTrue: cut(series.vTrue.toArray()),
      volume: vol,
      conf,
      iv: cut(series.iv.toArray()),
      atm: cut(series.atmCall.toArray()),
      mm: cut(series.mmInventory.toArray()),
      imbalance: cut(series.imbalance.toArray()),
      items,
      awareness,
      dayVol: vol.slice(-TICKS_PER_DAY).reduce((a, b) => a + b, 0),
    };
  }, [version, cursor]);

  const last = <T,>(a: T[]) => a[a.length - 1];
  const days = meta?.days ?? 5;
  const nAgents = meta?.n_nodes ?? meta?.n_agents ?? 1;
  const progress = data.n ? (series.tick.last() + 1) / (days * TICKS_PER_DAY) : 0;
  const live = status === "live" || status === "connecting" || status === "reconnecting";
  const finished = status === "done" || summary != null;

  // top 5 items by awareness at the cursor, coloured by birth order (stable per item)
  const top = useMemo(() => {
    const order = new Map(born.map((b, i) => [b.item, i]));
    const ids = Object.entries(data.awareness)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .map(([k]) => Number(k));
    const step = Math.max(1, Math.ceil(data.ticks.length / 300));
    const xs = data.ticks.filter((_, i) => i % step === 0 || i === data.ticks.length - 1);
    return {
      xs,
      series: ids.map((id) => {
        const h = awarenessHistory.get(id)!;
        const at = new Map(h.ticks.map((t, i) => [t, h.counts[i]!]));
        const meta = born.find((b) => b.item === id);
        let carry: number | null = null;
        const values = xs.map((t) => {
          const v = at.get(t);
          if (v != null) carry = v;
          return t < (h.ticks[0] ?? Infinity) ? null : carry;
        });
        return {
          key: String(id),
          label: `#${id} ${meta?.label ?? ""}`.slice(0, 40),
          values: values.map((v) => (v == null ? null : (100 * v) / nAgents)),
          color: CATEGORICAL[(order.get(id) ?? id) % CATEGORICAL.length]!,
        };
      }),
    };
  }, [data, nAgents]);

  async function replay() {
    const spec = run.data?.spec;
    if (!spec) return;
    try {
      const r = await create.mutateAsync({
        scenario: spec.scenario,
        parameters: spec.parameters as unknown as Schemas["Parameters"],
        seed: spec.seed,
        mode: "single",
        runs: 1,
        workers: 1,
        pace: 48,
      });
      setCursor(null);
      connectRun(r.id);
      toast.success("Replaying with the same seed", { description: `Identical results: ${r.id}` });
    } catch (e) {
      toast.error("Could not replay", { description: (e as Error).message });
    }
  }

  return (
    <div className="flex h-full min-h-[760px] flex-col gap-4 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="font-mono text-[11px] tracking-[0.16em] text-primary">
            {finished ? "RUN FINISHED" : "LIVE RUN"}
          </p>
          <h2 className="mt-1 truncate text-xl font-semibold tracking-tight">
            {meta
              ? `${run.data?.name ?? "Run"} · ${formatCompact(meta.n_agents)} agents · ${meta.days} days · seed ${meta.seed}`
              : "Connecting…"}
          </h2>
        </div>
        <ClockBadge tick={data.tick} />
        {runId && <Tag>{runId}</Tag>}
      </div>

      {/* playback */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border bg-card px-3 py-2">
        <Button
          size="sm"
          variant={cursor == null ? "default" : "outline"}
          onClick={() => setCursor(null)}
          aria-pressed={cursor == null}
        >
          <Radio />
          Live
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setCursor(cursor == null ? Math.max(0, data.n - 1) : null)}
          aria-label={cursor == null ? "Pause the display" : "Resume following the run"}
        >
          {cursor == null ? <Pause /> : <Play />}
          {cursor == null ? "Pause" : "Resume"}
        </Button>
        <input
          type="range"
          min={0}
          max={Math.max(0, data.n - 1)}
          value={cursor ?? Math.max(0, data.n - 1)}
          onChange={(e) => setCursor(Number(e.target.value))}
          aria-label="Scrub through the buffered frames"
          aria-valuetext={simClock(data.tick).label}
          className="h-1.5 min-w-40 flex-1 cursor-pointer accent-[var(--primary)]"
        />
        <span
          className="tabular w-28 text-right font-mono text-xs text-muted-foreground"
          title="Frames received in the last second"
        >
          {live ? `${fps} ticks/s` : status}
        </span>
        <Button
          size="sm"
          variant="outline"
          disabled={
            !live ||
            !run.data ||
            !["running", "queued"].includes(run.data.status) ||
            cancel.isPending
          }
          onClick={() =>
            runId &&
            cancel.mutate(runId, {
              onSuccess: () =>
                toast("Cancelling the run", {
                  description: "It stops within a tick and keeps what it computed.",
                }),
              onError: (e) => toast.error("Could not cancel", { description: e.message }),
            })
          }
        >
          <XCircle />
          Cancel run
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={!run.data || create.isPending}
          onClick={() => void replay()}
        >
          <RotateCcw />
          Replay with same seed
        </Button>
        {live && (
          <Button size="sm" variant="ghost" onClick={disconnectRun}>
            <Square />
            Stop watching
          </Button>
        )}
      </div>

      <div
        className="h-1 overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-label="Run progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(Math.min(1, progress) * 100)}
      >
        <motion.div
          className="h-full rounded-full bg-primary"
          animate={{ width: `${Math.min(1, progress) * 100}%` }}
          transition={progressTransition}
        />
      </div>

      <ResizableGroup orientation="horizontal" className="min-h-0 flex-1">
        <ResizablePanel defaultSize="68" minSize="45">
          <div className="flex h-full flex-col gap-4 pr-2">
            <Panel
              title="Price"
              subtitle="15-minute candles in market hours · dashed: hidden fundamental value · markers: news"
              icon={CandlestickChart}
              className="min-h-[380px] flex-1"
              actions={
                <>
                  <span className="tabular mr-2 font-mono text-sm font-semibold">
                    {formatPrice(last(data.price))}
                  </span>
                  <div
                    className="flex overflow-hidden rounded-md border"
                    role="group"
                    aria-label="Chart type"
                  >
                    <button
                      type="button"
                      aria-pressed={mode === "candles"}
                      onClick={() => setMode("candles")}
                      className={cn(
                        "grid size-7 place-items-center",
                        mode === "candles" ? "bg-primary/15 text-primary" : "text-muted-foreground",
                      )}
                      aria-label="Candles"
                    >
                      <CandlestickChart className="size-4" />
                    </button>
                    <button
                      type="button"
                      aria-pressed={mode === "line"}
                      onClick={() => setMode("line")}
                      className={cn(
                        "grid size-7 place-items-center border-l",
                        mode === "line" ? "bg-primary/15 text-primary" : "text-muted-foreground",
                      )}
                      aria-label="Line"
                    >
                      <LineChart className="size-4" />
                    </button>
                  </div>
                </>
              }
            >
              <PriceChart
                ticks={data.ticks}
                price={data.price}
                vTrue={data.vTrue}
                volume={data.volume}
                events={data.items}
                mode={mode}
                pulseKey={data.items.filter((i) => i.origin !== "price_news").length}
              />
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-1.5">
                  <span
                    className="h-0 w-4 border-t-2 border-dashed border-fundamental"
                    aria-hidden
                  />{" "}
                  Fundamental value (hidden from agents)
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="size-2.5 rounded-full bg-official" aria-hidden /> Official / news
                  (arrow)
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="size-2.5 rounded-full bg-narrative" aria-hidden /> Rumour /
                  narrative (circle)
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="size-2.5 rounded-[2px] bg-muted-foreground" aria-hidden /> Price
                  headline (square)
                </span>
              </div>
            </Panel>
            <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-4">
              <Panel
                title="Investor confidence"
                icon={Gauge}
                bodyClassName="grid place-items-center p-2"
              >
                <ConfidenceGauge value={last(data.conf) ?? null} label="Mean investor confidence" />
              </Panel>
              <div className="grid grid-cols-2 gap-4 2xl:grid-cols-1">
                <Stat
                  label="Implied vol"
                  value={last(data.iv)}
                  format={(v) => formatPct(v)}
                  hint="annualised"
                />
                <Stat
                  label="ATM call (30d)"
                  value={last(data.atm)}
                  format={(v) => formatPrice(v)}
                  hint="Black–Scholes"
                />
              </div>
              <Panel
                title="Market-maker inventory"
                subtitle="Shares absorbed by the market maker"
                icon={Activity}
              >
                <Sparkline
                  values={data.mm.length ? data.mm : [0]}
                  label="Market-maker inventory"
                  height={64}
                  interactive
                  format={(v) => formatCompact(v)}
                  xLabel={(i) => simClock(data.ticks[i] ?? 0).label}
                />
                <p className="tabular mt-1 font-mono text-sm">
                  {formatCompact(last(data.mm) ?? 0)} shares
                </p>
              </Panel>
              <Panel
                title="Order imbalance"
                subtitle="Retail buy vs sell orders, last auction"
                icon={Activity}
              >
                <ImbalanceMeter value={last(data.imbalance) ?? 0} />
                <p className="mt-3 text-xs text-muted-foreground">
                  Volume, last 24h:{" "}
                  <span className="tabular font-mono text-foreground">
                    {formatCompact(data.dayVol)}
                  </span>
                </p>
              </Panel>
            </div>
          </div>
        </ResizablePanel>
        <ResizableHandle />
        <ResizablePanel defaultSize="32" minSize="22">
          <div className="flex h-full flex-col gap-4 pl-2">
            <Panel
              title="Awareness"
              subtitle="Top 5 items, % of agents who have seen them"
              icon={Users}
            >
              {top.series.length ? (
                <XYChart
                  x={top.xs}
                  series={top.series}
                  height={170}
                  yFormat={(v) => `${v.toFixed(0)}%`}
                  xFormat={(t) => simClock(t).label.replace("Day ", "D")}
                  label="Awareness of the five most-seen items"
                />
              ) : (
                <p className="text-sm text-muted-foreground">No item is spreading yet.</p>
              )}
            </Panel>
            <Panel
              title="News feed"
              subtitle={`${data.items.length} items born`}
              icon={Newspaper}
              className="min-h-0 flex-1"
              bodyClassName="overflow-y-auto"
            >
              <NewsFeed items={data.items} awareness={data.awareness} nAgents={nAgents} />
            </Panel>
          </div>
        </ResizablePanel>
      </ResizableGroup>
      {finished && summary && (
        <p className="text-xs text-muted-foreground">
          Final price {formatPrice(summary.final_price as number)} (
          {formatSigned(((summary.return as number) ?? 0) * 100)}%) · open the Narratives and
          Network views for this run.
        </p>
      )}
    </div>
  );
}
