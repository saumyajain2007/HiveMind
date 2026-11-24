import { BookOpenText, GitBranch, Grid3x3, LineChart, Network as NetIcon, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";

import { SentimentChip, Tag } from "@/components/badges";
import { BarChart } from "@/components/charts/BarChart";
import { Heatmap } from "@/components/charts/Heatmap";
import { CATEGORICAL, DASHES, OTHER } from "@/components/charts/scale";
import { XYChart } from "@/components/charts/XYChart";
import { EmptyState } from "@/components/EmptyState";
import { Panel } from "@/components/Panel";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { LineageTree } from "@/features/narratives/LineageTree";
import { ORIGIN_LABEL } from "@/features/narratives/origins";
import { RunPicker } from "@/features/runs/RunPicker";
import { useSelectedRun } from "@/features/runs/useSelectedRun";
import { useAwareness, useLineage, useRun } from "@/lib/api/queries";
import type { Family, LineageItem } from "@/lib/api/results";
import { formatCompact, simClock, TICKS_PER_DAY } from "@/lib/format";
import { cn } from "@/lib/utils";
import { PLATFORMS } from "@/lib/vocab";
import type { PlatformName } from "@/lib/vocab";

const CATEGORY_LABEL: Record<string, string> = {
  non_investor: "Non-investors",
  long_term: "Long-term",
  swing: "Swing",
  day_trader: "Day traders",
  media: "Media",
};

const pct = (x: number) => `${(x * 100).toFixed(x < 0.1 ? 1 : 0)}%`;

/** Readable name: the headline, or what the engine made (mutations and inventions have none). */
function itemName(i: LineageItem): string {
  if (i.origin === "invention")
    return `made-up reason for the ${i.label === "up" ? "rise" : "fall"}`;
  if (i.origin === "mutation") return `distorted retelling of #${i.parent}`;
  return i.label || i.kind || ORIGIN_LABEL[i.origin];
}

/** "Rumour #0 (anonymous) → mutated twice → reached 41% of agents → denial #5 reached 28%". */
function story(f: Family, items: LineageItem[], nNodes: number): string {
  const members = items.filter((i) => i.root === f.root);
  const root = members.find((i) => i.id === f.root);
  const name = root?.label ?? root?.kind ?? f.origin;
  const kind = root?.kind || ORIGIN_LABEL[f.origin as LineageItem["origin"]];
  const head =
    root?.origin === "invention"
      ? `Invention #${f.root} (${itemName(root)})`
      : `${kind[0]!.toUpperCase() + kind.slice(1)} #${f.root}${root?.label ? ` “${name}”` : ""}`;
  const parts = [head];
  const muts = members.filter((i) => i.origin === "mutation").length;
  if (muts) parts.push(`mutated ${muts === 1 ? "once" : muts === 2 ? "twice" : `${muts} times`}`);
  parts.push(`reached ${pct(f.aware / nNodes)} of agents`);
  for (const fu of members.filter((i) => i.origin === "event" && i.id !== f.root))
    parts.push(
      `${fu.kind === "statement" ? "official statement" : fu.kind} #${fu.id} reached ${pct(fu.final_aware / nNodes)} on its own`,
    );
  return parts.join(" → ");
}

export function NarrativesPage() {
  const sel = useSelectedRun(["single"]);
  const run = useRun(sel.id);
  const done = run.data?.status === "done" || run.data?.status === "cancelled";
  const lineage = useLineage(done ? sel.id : null);
  const aw = useAwareness(done ? sel.id : null);
  const [selected, setSelected] = useState<number | null>(null);
  const [share, setShare] = useState(true);
  const [showPrice, setShowPrice] = useState(false);
  const [breakdown, setBreakdown] = useState<"heat" | "bars">("heat");
  const nTicks = (run.data?.days ?? 5) * TICKS_PER_DAY;
  const nNodes = aw.data?.n_nodes ?? 1;

  // colour follows the family (by root id), never its rank; price headlines are grey
  const families = useMemo(() => aw.data?.families ?? [], [aw.data]);
  const colorOf = useMemo(() => {
    const story = families
      .filter((f) => f.origin !== "price_news")
      .map((f) => f.root)
      .sort((a, b) => a - b);
    const map = new Map(story.slice(0, CATEGORICAL.length).map((r, i) => [r, CATEGORICAL[i]!]));
    return (root: number) => map.get(root) ?? OTHER;
  }, [families]);
  const visible = families.filter((f) => showPrice || f.origin !== "price_news");
  const items = useMemo(
    () => (lineage.data?.items ?? []).filter((i) => showPrice || i.origin !== "price_news"),
    [lineage.data, showPrice],
  );

  const curves = useMemo(() => {
    const x = Array.from({ length: Math.ceil(nTicks / 2) }, (_, i) => i * 2);
    return visible.map((f, k) => {
      const at = new Map(f.rows.map((r) => [r[0]!, r[2]!]));
      let carry: number | null = null;
      const start = f.rows[0]?.[0] ?? Infinity;
      const values = x.map((t) => {
        const v = at.get(t);
        if (v != null) carry = v;
        return t < start ? null : carry == null ? null : share ? (100 * carry) / nNodes : carry;
      });
      const root = lineage.data?.items.find((i) => i.id === f.root);
      return {
        key: String(f.root),
        label: `#${f.root} ${root?.label ?? f.kind ?? f.origin}`.slice(0, 44),
        values,
        color: colorOf(f.root),
        dash: DASHES[k % DASHES.length],
      };
    });
  }, [visible, nTicks, share, nNodes, colorOf, lineage.data]);

  const heat = useMemo(() => {
    if (!aw.data) return null;
    const P = aw.data.platforms.length;
    const cats = aw.data.categories;
    const catSize = aw.data.category_sizes ?? cats.map(() => 1);
    const platSize = aw.data.platform_sizes ?? aw.data.platforms.map(() => 1);
    const plats = aw.data.platforms
      .map((p, j) => [p, j] as const)
      .filter(([, j]) => (platSize[j] ?? 0) > 0);
    const rows = visible.map((f) => {
      const peak = f.rows.reduce((best, r) => (r[2]! > (best?.[2] ?? -1) ? r : best), f.rows[0]);
      const catVals = cats.map((_, c) => (peak ? peak[3 + P + c]! / Math.max(1, catSize[c]!) : 0));
      const platVals = plats.map(([, j]) => (peak ? peak[3 + j]! / Math.max(1, platSize[j]!) : 0));
      return [...catVals, ...platVals];
    });
    const cols = [
      ...cats.map((c) => CATEGORY_LABEL[c] ?? c),
      ...plats.map(([p]) => `${PLATFORMS[p as PlatformName]?.label ?? p} users`),
    ];
    return { rows, cols };
  }, [aw.data, visible]);

  const sel_item = lineage.data?.items.find((i) => i.id === selected) ?? null;
  const chain = useMemo(() => {
    if (!sel_item || !lineage.data) return [];
    const byId = new Map(lineage.data.items.map((i) => [i.id, i]));
    const out: LineageItem[] = [];
    let cur: LineageItem | undefined = sel_item;
    while (cur) {
      out.unshift(cur);
      cur = cur.parent >= 0 ? byId.get(cur.parent) : undefined;
    }
    return out;
  }, [sel_item, lineage.data]);

  if (!sel.loading && !sel.candidates.length) {
    return (
      <div className="grid min-h-full place-items-center p-6">
        <EmptyState
          icon={GitBranch}
          title="No finished run yet"
          description="Run a scenario; its narrative families, mutations and inventions appear here."
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
    <div className="mx-auto flex max-w-[1500px] flex-col gap-5 p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-mono text-[11px] tracking-[0.16em] text-primary">NARRATIVES</p>
          <h2 className="mt-1 text-2xl font-semibold tracking-tight">
            How the stories spread and changed
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {lineage.data
              ? `${lineage.data.items.length} items in ${families.length} families · ${formatCompact(nNodes)} agents`
              : "Loading…"}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={showPrice}
              onChange={(e) => setShowPrice(e.target.checked)}
            />
            Show price headlines
          </label>
          <RunPicker value={sel.id} candidates={sel.candidates} onChange={sel.select} />
        </div>
      </div>

      <Panel title="Story" icon={BookOpenText} subtitle="The lineage, read out">
        {lineage.data ? (
          <ol className="flex flex-col gap-1.5 text-sm">
            {families
              .filter((f) => f.origin !== "price_news" && f.aware > 0)
              .map((f) => (
                <li key={f.root} className="flex items-start gap-2">
                  <span
                    className="mt-1.5 size-2.5 shrink-0 rounded-full"
                    style={{ background: colorOf(f.root) }}
                    aria-hidden
                  />
                  <span>{story(f, lineage.data!.items, nNodes)}</span>
                </li>
              ))}
          </ol>
        ) : (
          <Skeleton className="h-16" />
        )}
      </Panel>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Panel
          title="Lineage"
          icon={GitBranch}
          subtitle="Hover an item to highlight its family · click for details"
        >
          {lineage.data ? (
            <LineageTree
              items={items}
              nTicks={nTicks}
              nNodes={nNodes}
              colorOf={colorOf}
              selected={selected}
              onSelect={setSelected}
            />
          ) : (
            <Skeleton className="h-[380px]" />
          )}
        </Panel>
        <Panel
          title={sel_item ? `#${sel_item.id} ${itemName(sel_item)}` : "Item"}
          icon={NetIcon}
          actions={
            sel_item && (
              <Button
                variant="ghost"
                size="icon"
                className="size-7"
                onClick={() => setSelected(null)}
                aria-label="Close item"
              >
                <X />
              </Button>
            )
          }
        >
          {!sel_item ? (
            <p className="text-sm text-muted-foreground">
              Click an item in the lineage to see how credibility decays down its chain and how many
              agents saw it over time.
            </p>
          ) : (
            <div className="flex flex-col gap-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <Tag>{ORIGIN_LABEL[sel_item.origin]}</Tag>
                <Tag>born {simClock(sel_item.born).label}</Tag>
                <SentimentChip value={sel_item.sentiment} />
              </div>
              <p className="text-xs text-muted-foreground">
                {formatCompact(sel_item.final_aware)} agents aware (
                {pct(sel_item.final_aware / nNodes)}) · {formatCompact(sel_item.total_shares)}{" "}
                shares
                {sel_item.retired >= 0 ? ` · faded ${simClock(sel_item.retired).label}` : ""}
              </p>
              <div>
                <h3 className="mb-1.5 text-xs font-medium text-muted-foreground">
                  Credibility down the chain
                </h3>
                <ol className="flex flex-col gap-1">
                  {chain.map((c) => (
                    <li key={c.id} className="flex items-center gap-2 text-xs">
                      <span className="w-28 truncate">
                        #{c.id} {ORIGIN_LABEL[c.origin]}
                      </span>
                      <span
                        className="relative h-2 flex-1 overflow-hidden rounded-full bg-muted"
                        aria-hidden
                      >
                        <span
                          className="absolute inset-y-0 left-0 rounded-full"
                          style={{ width: `${c.credibility * 100}%`, background: colorOf(c.root) }}
                        />
                      </span>
                      <span className="tabular w-10 text-right font-mono">
                        {c.credibility.toFixed(2)}
                      </span>
                    </li>
                  ))}
                </ol>
              </div>
              {aw.data?.items[String(sel_item.id)] && (
                <XYChart
                  x={aw.data.items[String(sel_item.id)]!.map((r) => r[0])}
                  series={[
                    {
                      key: "aware",
                      label: "Agents aware",
                      values: aw.data.items[String(sel_item.id)]!.map((r) => r[1]),
                      color: colorOf(sel_item.root),
                      area: true,
                    },
                  ]}
                  height={150}
                  xFormat={(t) => simClock(t).label}
                  yFormat={(v) => formatCompact(v)}
                  label={`Agents aware of item ${sel_item.id} over time`}
                />
              )}
            </div>
          )}
        </Panel>
      </div>

      <Panel
        title="Family awareness"
        icon={LineChart}
        subtitle="A family is a root item plus its mutations and follow-ups"
        actions={
          <div
            className="flex overflow-hidden rounded-md border text-xs"
            role="group"
            aria-label="Scale"
          >
            <button
              type="button"
              aria-pressed={share}
              onClick={() => setShare(true)}
              className={cn("px-2.5 py-1", share && "bg-primary/12 font-medium")}
            >
              % of agents
            </button>
            <button
              type="button"
              aria-pressed={!share}
              onClick={() => setShare(false)}
              className={cn("border-l px-2.5 py-1", !share && "bg-primary/12 font-medium")}
            >
              Agents
            </button>
          </div>
        }
      >
        {aw.data ? (
          <XYChart
            x={Array.from({ length: Math.ceil(nTicks / 2) }, (_, i) => i * 2)}
            series={curves}
            height={300}
            xFormat={(t) => simClock(t).label}
            xTicks={Array.from(
              { length: Math.ceil(nTicks / TICKS_PER_DAY) },
              (_, d) => d * TICKS_PER_DAY,
            )}
            yFormat={(v) => (share ? `${v.toFixed(0)}%` : formatCompact(v))}
            label="Awareness of each event family over time"
          />
        ) : (
          <Skeleton className="h-[300px]" />
        )}
      </Panel>

      <Panel
        title="Who heard it"
        icon={Grid3x3}
        subtitle="Peak share aware within each investor category and among each platform's users"
        actions={
          <div
            className="flex overflow-hidden rounded-md border text-xs"
            role="group"
            aria-label="Breakdown view"
          >
            <button
              type="button"
              aria-pressed={breakdown === "heat"}
              onClick={() => setBreakdown("heat")}
              className={cn("px-2.5 py-1", breakdown === "heat" && "bg-primary/12 font-medium")}
            >
              Heat map
            </button>
            <button
              type="button"
              aria-pressed={breakdown === "bars"}
              onClick={() => setBreakdown("bars")}
              className={cn(
                "border-l px-2.5 py-1",
                breakdown === "bars" && "bg-primary/12 font-medium",
              )}
            >
              Bars
            </button>
          </div>
        }
      >
        {heat && lineage.data ? (
          breakdown === "heat" ? (
            <Heatmap
              rows={visible.map(
                (f) =>
                  `#${f.root} ${lineage.data!.items.find((i) => i.id === f.root)?.label ?? f.kind}`,
              )}
              cols={heat.cols}
              values={heat.rows}
              rowColors={visible.map((f) => colorOf(f.root))}
              label="Share aware by family, category and platform"
            />
          ) : (
            <BarChart
              categories={heat.cols}
              groups={visible.slice(0, 6).map((f, k) => ({
                key: String(f.root),
                label:
                  `#${f.root} ${lineage.data!.items.find((i) => i.id === f.root)?.label ?? f.kind}`.slice(
                    0,
                    40,
                  ),
                color: colorOf(f.root),
                values: heat.rows[k]!,
              }))}
              height={300}
              yFormat={(v) => `${Math.round(v * 100)}%`}
              label="Share aware by family, category and platform"
            />
          )
        ) : (
          <Skeleton className="h-40" />
        )}
      </Panel>
    </div>
  );
}
