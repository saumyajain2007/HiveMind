import { Copy, ExternalLink, Library, Play, RefreshCw, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";

import { useDemoReplay } from "@/app/useDemoReplay";
import { StatusPill, Tag } from "@/components/badges";
import { Delta } from "@/components/Delta";
import { EmptyState } from "@/components/EmptyState";
import { Panel } from "@/components/Panel";
import { Sparkline } from "@/components/Sparkline";
import { Stat } from "@/components/Stat";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { RunRecord } from "@/lib/api/client";
import { useDeleteRun, useRuns } from "@/lib/api/queries";
import { api, unwrap } from "@/lib/api/client";
import type { Schemas } from "@/lib/api/client";
import { builderStore } from "@/features/builder/store";
import type { Parameters } from "@/features/builder/store";
import { RunCompare } from "@/features/runs/RunCompare";
import {
  formatCompact,
  formatPrice,
  formatRelative,
  formatSignedPct,
  shortHash,
} from "@/lib/format";

function num(x: unknown): number | null {
  return typeof x === "number" && Number.isFinite(x) ? x : null;
}

export function RunsPage() {
  const runs = useRuns();
  const demo = useDemoReplay();
  const items = useMemo(() => runs.data?.items ?? [], [runs.data]);
  const [compare, setCompare] = useState<string[]>([]);
  const toggleCompare = (id: string) =>
    setCompare((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id].slice(-2)));

  const stats = useMemo(() => {
    const done = items.filter((r) => r.status === "done");
    const moves = done.map((r) => num(r.summary?.return)).filter((x): x is number => x != null);
    const sorted = [...moves].sort((a, b) => a - b);
    const median = sorted.length ? sorted[Math.floor(sorted.length / 2)]! : null;
    return {
      total: runs.data?.total ?? 0,
      running: items.filter((r) => r.status === "running" || r.status === "queued").length,
      done: done.length,
      agents: items.reduce((a, r) => a + r.n_agents * r.runs, 0),
      median,
      moves: [...moves].reverse(),
    };
  }, [items, runs.data]);

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-5 p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-mono text-[11px] tracking-[0.16em] text-primary">RUN LIBRARY</p>
          <h2 className="mt-1 text-2xl font-semibold tracking-tight">Simulation runs</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Every run is fully determined by its spec; equal spec hashes give identical results.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void runs.refetch()}
            disabled={runs.isFetching}
          >
            <RefreshCw className={runs.isFetching ? "motion-safe:animate-spin" : undefined} />
            Refresh
          </Button>
          <Button size="sm" onClick={() => void demo.start()} disabled={demo.pending}>
            <Play />
            Run demo scenario
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label="Runs"
          value={stats.total}
          loading={runs.isPending}
          hint={`${stats.done} finished`}
        />
        <Stat
          label="In progress"
          value={stats.running}
          loading={runs.isPending}
          hint="queued or running"
        />
        <Stat
          label="Agents simulated"
          value={stats.agents}
          loading={runs.isPending}
          hint="across all repetitions"
        />
        <Stat
          label="Median 5-day move"
          value={stats.median}
          format={(v) => formatSignedPct(v)}
          loading={runs.isPending}
          trend={stats.moves.length > 1 ? stats.moves : undefined}
          trendLabel="Final move of each finished run, oldest first"
          hint="finished runs"
        />
      </div>

      <Panel
        title="All runs"
        subtitle={runs.data ? `${runs.data.total} total` : "Loading…"}
        icon={Library}
        bodyClassName="p-0"
        index={1}
      >
        {runs.isPending ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-11 w-full" />
            ))}
          </div>
        ) : runs.isError ? (
          <EmptyState
            icon={Library}
            title="Could not load runs"
            description="The API did not answer. Start it with `uv run uvicorn marketsim_api.main:app`, or run the web app with VITE_API_MOCK=true."
            actions={
              <Button variant="outline" onClick={() => void runs.refetch()}>
                Try again
              </Button>
            }
          />
        ) : items.length === 0 ? (
          <EmptyState
            icon={Library}
            title="No runs yet"
            description="Start with the demo: an anonymous takeover rumour, an official denial, then a real earnings miss."
            actions={
              <Button onClick={() => void demo.start()}>
                <Play />
                Run demo scenario
              </Button>
            }
          />
        ) : (
          <RunsTable items={items} compare={compare} onToggleCompare={toggleCompare} />
        )}
      </Panel>
      {compare.length === 2 && <RunCompare a={compare[0]!} b={compare[1]!} />}
    </div>
  );
}

const OPEN: Record<string, (id: string) => string> = {
  single: (id) => `/narratives?run=${id}`,
  montecarlo: (id) => `/monte-carlo?run=${id}`,
  calibration: () => "/analysis",
  backtest: () => "/analysis",
};

function RowActions({ r }: { r: RunRecord }) {
  const del = useDeleteRun();
  const navigate = useNavigate();
  const [confirm, setConfirm] = useState(false);
  const active = r.status === "running" || r.status === "queued";
  async function duplicate() {
    try {
      const d = unwrap(
        await api.GET("/api/v1/runs/{run_id}", { params: { path: { run_id: r.id } } }),
      );
      builderStore
        .getState()
        .load(
          { ...d.spec.scenario, name: `${d.spec.scenario.name} (copy)` } as Schemas["ScenarioSpec"],
          null,
          d.spec.parameters as unknown as Parameters,
        );
      navigate("/builder");
      toast.success("Copied into the Builder", { description: r.name });
    } catch (e) {
      toast.error("Could not load the run", { description: (e as Error).message });
    }
  }
  return (
    <div className="flex items-center justify-end gap-1">
      <Button variant="ghost" size="icon" className="size-7" asChild aria-label={`Open ${r.name}`}>
        <Link to={(OPEN[r.mode] ?? OPEN.single!)(r.id)}>
          <ExternalLink />
        </Link>
      </Button>
      {(r.mode === "single" || r.mode === "montecarlo") && (
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          onClick={() => void duplicate()}
          aria-label={`Duplicate ${r.name} into the Builder`}
        >
          <Copy />
        </Button>
      )}
      {confirm ? (
        <Button
          variant="outline"
          size="sm"
          className="h-7 text-bear-text"
          onClick={() =>
            del.mutate(r.id, {
              onSuccess: () => toast.success("Run deleted"),
              onError: (e) => toast.error("Could not delete", { description: e.message }),
            })
          }
          onBlur={() => setConfirm(false)}
          autoFocus
        >
          Delete?
        </Button>
      ) : (
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          disabled={active}
          onClick={() => setConfirm(true)}
          aria-label={active ? `${r.name} is still running` : `Delete ${r.name}`}
        >
          <Trash2 />
        </Button>
      )}
    </div>
  );
}

function RunsTable({
  items,
  compare,
  onToggleCompare,
}: {
  items: RunRecord[];
  compare: string[];
  onToggleCompare: (id: string) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1000px] text-sm">
        <thead>
          <tr className="border-b text-left text-xs text-muted-foreground">
            <th scope="col" className="px-4 py-2.5 font-medium">
              Run
            </th>
            <th scope="col" className="px-3 py-2.5 font-medium">
              Status
            </th>
            <th scope="col" className="px-3 py-2.5 text-right font-medium">
              Agents
            </th>
            <th scope="col" className="px-3 py-2.5 text-right font-medium">
              Days
            </th>
            <th scope="col" className="px-3 py-2.5 font-medium">
              Daily closes
            </th>
            <th scope="col" className="px-3 py-2.5 text-right font-medium">
              Final
            </th>
            <th scope="col" className="px-3 py-2.5 font-medium">
              Spec
            </th>
            <th scope="col" className="px-3 py-2.5 text-right font-medium">
              Created
            </th>
            <th scope="col" className="px-2 py-2.5 text-center font-medium">
              Compare
            </th>
            <th scope="col" className="px-4 py-2.5 text-right font-medium">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((r) => {
            const spark = Array.isArray(r.summary?.price_spark)
              ? (r.summary.price_spark as number[])
              : null;
            const final = num(r.summary?.final_price);
            const ret = num(r.summary?.return);
            return (
              <tr
                key={r.id}
                className="border-b transition-colors last:border-0 hover:bg-surface-2/60"
              >
                <th scope="row" className="px-4 py-3 text-left font-normal">
                  <div className="font-medium">{r.name}</div>
                  <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
                    <span className="font-mono">{r.id}</span>
                    <Tag>{r.mode === "montecarlo" ? `MC ×${r.runs}` : r.mode}</Tag>
                    <span className="font-mono">seed {r.seed}</span>
                  </div>
                </th>
                <td className="px-3 py-3">
                  <StatusPill status={r.status} />
                  {r.error && (
                    <p
                      className="mt-1 max-w-[220px] truncate text-xs text-bear-text"
                      title={r.error}
                    >
                      {r.error}
                    </p>
                  )}
                </td>
                <td className="tabular px-3 py-3 text-right font-mono">
                  {formatCompact(r.n_agents)}
                </td>
                <td className="tabular px-3 py-3 text-right font-mono">{r.days}</td>
                <td className="w-[160px] px-3 py-3">
                  {spark && spark.length > 1 ? (
                    <Sparkline
                      values={spark}
                      label={`${r.name}: daily closing prices`}
                      height={28}
                      area={false}
                      format={(v) => formatPrice(v)}
                    />
                  ) : (
                    <span className="text-xs text-muted-foreground">—</span>
                  )}
                </td>
                <td className="px-3 py-3 text-right">
                  <div className="tabular font-mono">
                    {final != null ? formatPrice(final) : "—"}
                  </div>
                  {ret != null && <Delta value={ret} />}
                </td>
                <td className="px-3 py-3">
                  <span className="font-mono text-xs text-muted-foreground" title={r.spec_hash}>
                    {shortHash(r.spec_hash)}
                  </span>
                </td>
                <td className="px-3 py-3 text-right text-xs whitespace-nowrap text-muted-foreground">
                  <time dateTime={r.created_at}>{formatRelative(r.created_at)}</time>
                </td>
                <td className="px-2 py-3 text-center">
                  <input
                    type="checkbox"
                    checked={compare.includes(r.id)}
                    onChange={() => onToggleCompare(r.id)}
                    aria-label={`Compare ${r.name}`}
                  />
                </td>
                <td className="px-4 py-3">
                  <RowActions r={r} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
