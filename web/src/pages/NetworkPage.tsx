import { BarChart3, Network, Pause, Play, Radio, Users } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";

import { PlatformIcon, Tag } from "@/components/badges";
import { BarChart } from "@/components/charts/BarChart";
import { EmptyState } from "@/components/EmptyState";
import { Panel } from "@/components/Panel";
import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { GraphView } from "@/features/network/GraphView";
import type { SpreadState } from "@/features/network/GraphView";
import { RunPicker } from "@/features/runs/RunPicker";
import { useSelectedRun } from "@/features/runs/useSelectedRun";
import { useGraph, useLineage, useNodeSeen, useRun } from "@/lib/api/queries";
import type { GraphNode } from "@/lib/api/results";
import { formatCompact, simClock, TICKS_PER_DAY } from "@/lib/format";
import { useLive } from "@/lib/live/store";
import { useReducedMotion } from "motion/react";
import { cn } from "@/lib/utils";
import { PLATFORMS } from "@/lib/vocab";
import type { PlatformName } from "@/lib/vocab";

const NARRATIVE_KINDS = new Set(["rumour", "leak", "mutation", "invention"]);

function StatsDrawer({
  open,
  onOpenChange,
  stats,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  stats: Record<string, Record<string, unknown>>;
}) {
  const layers = Object.entries(stats).filter(([k]) => k !== "overlap_jaccard");
  const overlap = (stats.overlap_jaccard ?? {}) as Record<string, number>;
  const pct = (d: unknown) =>
    d as { mean: number; p50: number; p90: number; p99: number; max: number };
  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
      title="Layer statistics"
      description="Computed on the whole population, not just the sample (graph.layer_stats())"
    >
      <div className="flex flex-col gap-5">
        {layers.map(([name, s]) => {
          const deg = pct(s.in_degree ?? s.degree ?? s.memberships_per_user);
          const label = s.in_degree
            ? "Followers per user"
            : s.degree
              ? "Friends per user"
              : "Subreddits per user";
          return (
            <section key={name} className="flex flex-col gap-2 rounded-lg border p-3">
              <div className="flex items-center gap-2">
                {name in PLATFORMS ? (
                  <PlatformIcon platform={name as PlatformName} />
                ) : (
                  <span>{name}</span>
                )}
                <Tag>{String(s.kind)}</Tag>
                <span className="ml-auto font-mono text-xs text-muted-foreground">
                  {formatCompact(Number(s.users))} users ·{" "}
                  {formatCompact(Number(s.edges ?? s.memberships))}{" "}
                  {s.edges ? "edges" : "memberships"}
                </span>
              </div>
              {deg && (
                <BarChart
                  categories={["mean", "median", "p90", "p99", "max"]}
                  groups={[
                    {
                      key: name,
                      label,
                      color: PLATFORMS[name as PlatformName]?.color ?? "var(--primary)",
                      values: [deg.mean, deg.p50, deg.p90, deg.p99, deg.max],
                    },
                  ]}
                  height={150}
                  yFormat={(v) => formatCompact(v)}
                  label={`${label} on ${name}`}
                />
              )}
              <p className="text-xs text-muted-foreground">
                {label}
                {s.reciprocity != null &&
                  ` · reciprocity ${(Number(s.reciprocity) * 100).toFixed(1)}%`}
                {s.clustering != null && ` · clustering ${Number(s.clustering).toFixed(3)}`}
                {s.in_max_over_median != null &&
                  ` · max / median ${Number(s.in_max_over_median).toFixed(1)}`}
              </p>
            </section>
          );
        })}
        {Object.keys(overlap).length > 0 && (
          <section className="flex flex-col gap-1">
            <h3 className="text-sm font-medium">Edge overlap between layers (Jaccard)</h3>
            {Object.entries(overlap).map(([k, v]) => (
              <p key={k} className="flex justify-between font-mono text-xs">
                <span>{k.replace("~", " ∩ ")}</span>
                <span>{v.toFixed(4)}</span>
              </p>
            ))}
          </section>
        )}
      </div>
    </Sheet>
  );
}

export function NetworkPage() {
  const sel = useSelectedRun(["single"]);
  const run = useRun(sel.id);
  const done = run.data?.status === "done" || run.data?.status === "cancelled";
  const graph = useGraph(done ? sel.id : null, "all", 2000);
  const lineage = useLineage(done ? sel.id : null);
  const seen = useNodeSeen(done ? sel.id : null);
  const reduced = useReducedMotion() ?? false;
  const liveRun = useLive((s) => s.runId);
  const liveTick = useLive((s) => s.last?.tick ?? null);
  const [layer, setLayer] = useState("all");
  const [family, setFamily] = useState<number | null>(null);
  const [tick, setTick] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [followLive, setFollowLive] = useState(false);
  const [hover, setHover] = useState<(GraphNode & { x: number; y: number }) | null>(null);
  const [statsOpen, setStatsOpen] = useState(false);
  const nTicks = (run.data?.days ?? 5) * TICKS_PER_DAY;

  const families = useMemo(
    () => (lineage.data?.families ?? []).filter((f) => f.origin !== "price_news" && f.aware > 0),
    [lineage.data],
  );
  const fam =
    family ?? families.find((f) => f.kind === "rumour")?.root ?? families[0]?.root ?? null;
  const famMeta = families.find((f) => f.root === fam);

  // first tick each sampled node saw any item of the family
  const firstSeen = useMemo(() => {
    const out = new Map<number, number>();
    if (!graph.data || !seen.data || !lineage.data || fam == null) return out;
    const rootOf = new Map(lineage.data.items.map((i) => [i.id, i.root]));
    const idOfIndex = new Map(graph.data.nodes.map((n) => [n.index, n.id]));
    for (const [t, idx, item] of seen.data.rows) {
      if (rootOf.get(item) !== fam) continue;
      const id = idOfIndex.get(idx);
      if (id == null) continue;
      const prev = out.get(id);
      if (prev == null || t < prev) out.set(id, t);
    }
    return out;
  }, [graph.data, seen.data, lineage.data, fam]);

  const shownTick = followLive && liveRun === sel.id && liveTick != null ? liveTick : tick;
  const spread: SpreadState | null = useMemo(
    () =>
      fam == null
        ? null
        : {
            firstSeen,
            tick: shownTick,
            colorToken: NARRATIVE_KINDS.has(famMeta?.kind || famMeta?.origin || "")
              ? "--narrative"
              : "--official",
          },
    [fam, firstSeen, shownTick, famMeta],
  );
  const awareNow = useMemo(
    () => [...firstSeen.values()].filter((t) => t <= shownTick).length,
    [firstSeen, shownTick],
  );

  // playback: ~12 ticks per second
  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(
      () => {
        setTick((t) => {
          if (t >= nTicks - 1) {
            setPlaying(false);
            return t;
          }
          return Math.min(nTicks - 1, t + (reduced ? 8 : 1));
        });
      },
      reduced ? 400 : 80,
    );
    return () => window.clearInterval(id);
  }, [playing, nTicks, reduced]);

  if (!sel.loading && !sel.candidates.length) {
    return (
      <div className="grid min-h-full place-items-center p-6">
        <EmptyState
          icon={Network}
          title="No finished run yet"
          description="Run a scenario live; its sampled network and the spread of each rumour appear here."
          actions={
            <Button asChild>
              <Link to="/builder">Open the Builder</Link>
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-[720px] flex-col gap-4 p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-mono text-[11px] tracking-[0.16em] text-primary">NETWORK</p>
          <h2 className="mt-1 text-2xl font-semibold tracking-tight">
            Rumours spreading through the platforms
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {graph.data
              ? `${formatCompact(graph.data.nodes.length)} sampled agents of ${formatCompact(graph.data.n_nodes)} · ${formatCompact(graph.data.edges.length)} ties among them`
              : "Loading the sampled network…"}
          </p>
        </div>
        <RunPicker value={sel.id} candidates={sel.candidates} onChange={sel.select} />
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-xl border bg-card px-3 py-2">
        <div className="flex flex-wrap gap-1" role="group" aria-label="Layer">
          {["all", ...(graph.data?.layers ?? [])].map((l) => (
            <button
              key={l}
              type="button"
              aria-pressed={layer === l}
              onClick={() => setLayer(l)}
              className={cn(
                "rounded-md border px-2.5 py-1 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
                layer === l
                  ? "border-primary/50 bg-primary/10"
                  : "border-transparent hover:bg-muted",
              )}
            >
              {l === "all" ? "All layers" : <PlatformIcon platform={l as PlatformName} />}
            </button>
          ))}
        </div>
        <label className="ml-2 flex items-center gap-2 text-xs text-muted-foreground">
          Spread of
          <select
            className="h-8 max-w-72 rounded-md border bg-surface-2 px-2 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            value={fam ?? ""}
            onChange={(e) => {
              setFamily(Number(e.target.value));
              setTick(0);
            }}
          >
            {families.map((f) => (
              <option key={f.root} value={f.root}>
                #{f.root} {f.label ?? f.kind ?? f.origin} ({f.members} item
                {f.members === 1 ? "" : "s"})
              </option>
            ))}
          </select>
        </label>
        <Button
          variant="outline"
          size="sm"
          className="ml-auto"
          onClick={() => setStatsOpen(true)}
          disabled={!graph.data}
        >
          <BarChart3 />
          Layer stats
        </Button>
      </div>

      <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
        <Panel
          title="Sampled network"
          subtitle="Size: influence (log) · edge colour: platform · lit nodes have seen the selected story"
          icon={Network}
          className="min-h-[520px]"
          bodyClassName="relative p-0"
        >
          {graph.data && sel.id ? (
            <GraphView
              data={graph.data}
              runId={sel.id}
              layer={layer}
              spread={spread}
              onHover={setHover}
            />
          ) : (
            <Skeleton className="m-4 h-[480px]" />
          )}
          {hover && (
            <div
              className="pointer-events-none absolute z-20 w-60 rounded-lg border bg-popover/95 p-3 text-xs shadow-xl backdrop-blur"
              style={{ left: hover.x + 14, top: hover.y + 14 }}
            >
              <p className="font-medium">
                Agent {hover.id} · {hover.category.replace("_", " ")}
              </p>
              <dl className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-0.5 font-mono text-[11px]">
                <dt className="text-muted-foreground">influence</dt>
                <dd>{hover.influence.toFixed(1)}</dd>
                <dt className="text-muted-foreground">age</dt>
                <dd>{hover.age.toFixed(0)}</dd>
                <dt className="text-muted-foreground">knowledge</dt>
                <dd>{hover.knowledge.toFixed(2)}</dd>
                <dt className="text-muted-foreground">impulsiveness</dt>
                <dd>{hover.impulsiveness.toFixed(2)}</dd>
                <dt className="text-muted-foreground">wealth</dt>
                <dd>{formatCompact(hover.wealth)}</dd>
                <dt className="text-muted-foreground">community</dt>
                <dd>{hover.community}</dd>
              </dl>
              <p className="mt-1.5 text-muted-foreground">
                {hover.platforms.join(" · ") || "no platforms"}
              </p>
              <p className="mt-1 border-t pt-1">
                {firstSeen.has(hover.id)
                  ? `Saw it at ${simClock(firstSeen.get(hover.id)!).label}`
                  : "Never saw this story"}
              </p>
            </div>
          )}
        </Panel>

        <div className="flex flex-col gap-4">
          <Panel
            title="Spread"
            icon={Users}
            subtitle={famMeta ? `#${famMeta.root} ${famMeta.label ?? famMeta.kind}` : undefined}
          >
            <p className="tabular font-mono text-2xl font-semibold">
              {awareNow}
              <span className="text-sm font-normal text-muted-foreground">
                {" "}
                / {graph.data?.nodes.length ?? 0} sampled
              </span>
            </p>
            <p className="text-xs text-muted-foreground">
              aware at {simClock(shownTick).label}; {firstSeen.size} by the end of the run
            </p>
            <div className="mt-3 flex items-center gap-2">
              <Button size="sm" onClick={() => setPlaying((p) => !p)} disabled={followLive}>
                {playing ? <Pause /> : <Play />}
                {playing ? "Pause" : "Play"}
              </Button>
              <Button
                size="sm"
                variant={followLive ? "secondary" : "ghost"}
                disabled={liveRun !== sel.id}
                aria-pressed={followLive}
                onClick={() => setFollowLive((f) => !f)}
                title={
                  liveRun === sel.id
                    ? "Follow the Cockpit's clock"
                    : "This run is not open in the Cockpit"
                }
              >
                <Radio />
                Follow cockpit
              </Button>
            </div>
            <input
              type="range"
              min={0}
              max={nTicks - 1}
              value={shownTick}
              onChange={(e) => {
                setFollowLive(false);
                setPlaying(false);
                setTick(Number(e.target.value));
              }}
              aria-label="Spread clock"
              aria-valuetext={simClock(shownTick).label}
              className="mt-3 h-1.5 w-full cursor-pointer accent-[var(--primary)]"
            />
          </Panel>
          <Panel title="Legend" icon={Network}>
            <ul className="flex flex-col gap-2 text-xs">
              <li className="flex items-center gap-2">
                <span className="size-3 rounded-full bg-muted-foreground/60" aria-hidden /> Has not
                seen it yet
              </li>
              <li className="flex items-center gap-2">
                <span
                  className={cn(
                    "size-3 rounded-full",
                    spread?.colorToken === "--official" ? "bg-official" : "bg-narrative",
                  )}
                  aria-hidden
                />{" "}
                Has seen it
              </li>
              <li className="flex items-center gap-2">
                <span className="size-3.5 rounded-full bg-foreground" aria-hidden /> Saw it in the
                last hour (edges glow)
              </li>
              {(graph.data?.layers ?? []).map((l) => (
                <li key={l} className="flex items-center gap-2">
                  <span
                    className="h-0.5 w-4"
                    style={{ background: PLATFORMS[l as PlatformName]?.color }}
                    aria-hidden
                  />
                  {PLATFORMS[l as PlatformName]?.label ?? l} tie
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>
      {graph.data && (
        <StatsDrawer open={statsOpen} onOpenChange={setStatsOpen} stats={graph.data.stats} />
      )}
    </div>
  );
}
