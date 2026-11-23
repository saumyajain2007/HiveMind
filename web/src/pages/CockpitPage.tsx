import { Activity, Gauge, Megaphone, Newspaper, Play, Sparkles, Square, Wand2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useMemo } from "react";

import { useDemoReplay } from "@/app/useDemoReplay";
import { SentimentChip, Tag } from "@/components/badges";
import { EmptyState } from "@/components/EmptyState";
import { Panel } from "@/components/Panel";
import { Sparkline } from "@/components/Sparkline";
import { Stat } from "@/components/Stat";
import { Button } from "@/components/ui/button";
import { ResizableGroup, ResizableHandle, ResizablePanel } from "@/components/ui/resizable";
import {
  formatCompact,
  formatPct,
  formatPrice,
  formatSigned,
  simClock,
  TICKS_PER_DAY,
} from "@/lib/format";
import { disconnectRun, series, useLive, useLiveVersion } from "@/lib/live/store";
import type { FeedItem } from "@/lib/live/types";
import { cn } from "@/lib/utils";
import { useMotionTransition } from "@/lib/motion";

const MAX_POINTS = 600;

/** Every k-th point so long runs stay cheap to draw (the full series stays in the buffer). */
function downsample(xs: number[], max = MAX_POINTS): number[] {
  if (xs.length <= max) return xs;
  const step = xs.length / max;
  const out: number[] = [];
  for (let i = 0; i < max - 1; i++) out.push(xs[Math.floor(i * step)]!);
  out.push(xs[xs.length - 1]!);
  return out;
}

export function CockpitPage() {
  const status = useLive((s) => s.status);
  const demo = useDemoReplay();

  if (status === "idle") {
    return (
      <div className="grid min-h-full place-items-center p-6">
        <EmptyState
          icon={Activity}
          title="No live run"
          description="Start a run to watch the price, beliefs and news move tick by tick. The full cockpit (candles, event markers, playback) is built in issue #21."
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

function LiveCockpit() {
  const version = useLiveVersion();
  const last = useLive((s) => s.last);
  const meta = useLive((s) => s.meta);
  const status = useLive((s) => s.status);
  const runId = useLive((s) => s.runId);

  const data = useMemo(() => {
    void version; // re-read the ring buffers whenever new frames were flushed
    const ticks = series.tick.toArray();
    const price = series.price.toArray();
    const vTrue = series.vTrue.toArray();
    const conf = series.confidence.toArray();
    const vol = series.volume.toArray();
    const k = Math.max(1, Math.ceil(price.length / MAX_POINTS));
    const dayVol = vol.slice(-TICKS_PER_DAY).reduce((a, b) => a + b, 0);
    return {
      ticks: k > 1 ? ticks.filter((_, i) => i % k === 0 || i === ticks.length - 1) : ticks,
      price: downsample(price),
      vTrue: downsample(vTrue),
      conf: downsample(conf, 200),
      dayVol,
      confNow: conf[conf.length - 1] ?? null,
      confPrev: conf[Math.max(0, conf.length - 1 - TICKS_PER_DAY)] ?? null,
    };
  }, [version]);

  const progressTransition = useMotionTransition({ duration: 0.3 });
  const days = meta?.days ?? 5;
  const progress = last ? (last.tick + 1) / (days * TICKS_PER_DAY) : 0;

  return (
    <div className="flex h-full min-h-[640px] flex-col gap-4 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="font-mono text-[11px] tracking-[0.16em] text-primary">LIVE RUN</p>
          <h2 className="mt-1 truncate text-xl font-semibold tracking-tight">
            {meta
              ? `${formatCompact(meta.n_agents)} agents · ${meta.days} days · seed ${meta.seed}`
              : "Connecting…"}
          </h2>
        </div>
        <Tag>{runId}</Tag>
        {(status === "live" || status === "reconnecting" || status === "connecting") && (
          <Button variant="outline" size="sm" onClick={disconnectRun}>
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
        aria-valuenow={Math.round(progress * 100)}
      >
        <motion.div
          className="h-full rounded-full bg-primary"
          animate={{ width: `${progress * 100}%` }}
          transition={progressTransition}
        />
      </div>

      <ResizableGroup orientation="horizontal" className="min-h-0 flex-1">
        <ResizablePanel defaultSize="66" minSize="40">
          <div className="flex h-full flex-col gap-4">
            <Panel
              title="Price"
              subtitle="Solid: traded price · dashed: hidden fundamental value"
              icon={Activity}
              className="flex-1"
              actions={
                <span className="tabular font-mono text-sm font-semibold">
                  {formatPrice(last?.price)}
                </span>
              }
            >
              <div className="flex h-full min-h-[260px] flex-col">
                <Sparkline
                  values={data.price}
                  reference={data.vTrue}
                  referenceLabel="Fundamental"
                  label="Price over the run"
                  height="fill"
                  showRange
                  interactive
                  format={(v) => formatPrice(v)}
                  xLabel={(i) => simClock(data.ticks[i] ?? 0).label}
                  className="min-h-[240px] flex-1"
                />
                <div className="mt-3 flex items-center gap-4 text-xs text-muted-foreground">
                  <span className="inline-flex items-center gap-1.5">
                    <span aria-hidden className="h-0.5 w-4 rounded bg-primary" /> Price
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span
                      aria-hidden
                      className="h-0 w-4 border-t-2 border-dashed border-fundamental"
                    />{" "}
                    Fundamental value (hidden from agents)
                  </span>
                  <span className="ml-auto">
                    Hover or focus the chart and use ← → to read values
                  </span>
                </div>
              </div>
            </Panel>
            <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
              <Stat
                label="Mean investor confidence"
                value={data.confNow}
                format={(v) => formatSigned(v)}
                delta={
                  data.confNow != null && data.confPrev != null
                    ? data.confNow - data.confPrev
                    : null
                }
                deltaFormat={(x) => formatSigned(x)}
                period="vs a day ago"
                trend={data.conf}
              />
              <Stat label="Volume, last 24h" value={data.dayVol} hint="shares" />
              <Stat
                label="Implied vol"
                value={last?.iv}
                format={(v) => formatPct(v)}
                hint="annualised"
              />
              <Stat
                label="ATM call (30d)"
                value={last?.atm_call}
                format={(v) => formatPrice(v)}
                hint="Black–Scholes"
              />
            </div>
          </div>
        </ResizablePanel>
        <ResizableHandle aria-label="Resize news feed" />
        <ResizablePanel defaultSize="34" minSize="22">
          <NewsFeed />
        </ResizablePanel>
      </ResizableGroup>
    </div>
  );
}

const ORIGIN = {
  event: { icon: Megaphone, label: "Event", cls: "text-official-text" },
  mutation: { icon: Wand2, label: "Mutation", cls: "text-narrative-text" },
  invention: { icon: Sparkles, label: "Invented", cls: "text-narrative-text" },
  price_news: { icon: Newspaper, label: "Price headline", cls: "text-muted-foreground" },
} as const;

function NewsFeed() {
  const feed = useLive((s) => s.feed);
  const last = useLive((s) => s.last);
  return (
    <Panel
      title="News & narratives"
      subtitle={`${feed.length} items`}
      icon={Gauge}
      className="h-full"
      bodyClassName="overflow-y-auto p-2"
    >
      {feed.length === 0 ? (
        <p className="p-6 text-center text-sm text-muted-foreground">
          Nothing has happened yet. Events appear here as they are injected.
        </p>
      ) : (
        <ol className="flex flex-col gap-1.5" aria-label="News feed, newest first">
          <AnimatePresence initial={false}>
            {feed.map((item) => (
              <FeedRow
                key={`${item.type}-${item.id}`}
                item={item}
                aware={last?.awareness?.[String(item.id)]}
              />
            ))}
          </AnimatePresence>
        </ol>
      )}
    </Panel>
  );
}

function FeedRow({ item, aware }: { item: FeedItem; aware: number | undefined }) {
  const origin = item.type === "event" ? ORIGIN.event : ORIGIN[item.origin];
  const Icon = origin.icon;
  const parent = item.type === "narrative" && item.parent >= 0 ? item.parent : null;
  const rowTransition = useMotionTransition({ duration: 0.3 });
  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: -6, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={rowTransition}
      className="rounded-lg border bg-surface-2/50 p-3"
    >
      <div className="flex items-center gap-2 text-xs">
        <Icon className={cn("size-3.5", origin.cls)} aria-hidden />
        <span className={cn("font-medium", origin.cls)}>
          {item.type === "event" ? `${item.kind} · ${item.seeding}` : origin.label}
        </span>
        <span className="tabular ml-auto font-mono text-muted-foreground">
          {simClock(item.tick).label}
        </span>
      </div>
      <p className="mt-1.5 text-sm leading-snug">{item.label ?? `Item #${item.id}`}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <SentimentChip value={item.sentiment} compact />
        <span
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground"
          aria-label={`Credibility ${Math.round(item.credibility * 100)}%`}
        >
          <span aria-hidden className="h-1.5 w-12 overflow-hidden rounded-full bg-muted">
            <span
              className="block h-full rounded-full bg-muted-foreground"
              style={{ width: `${item.credibility * 100}%` }}
            />
          </span>
          cred {Math.round(item.credibility * 100)}%
        </span>
        {aware != null && (
          <span className="tabular ml-auto font-mono text-xs">
            {formatCompact(aware)} <span className="text-muted-foreground">aware</span>
          </span>
        )}
      </div>
      {parent != null && (
        <p className="mt-1.5 text-xs text-muted-foreground">Mutated from #{parent}</p>
      )}
    </motion.li>
  );
}
