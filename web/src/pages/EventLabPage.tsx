import { Beaker, Boxes, FlaskConical, Layers, Library, Play, Split, Zap } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/EmptyState";
import { BarChart } from "@/components/charts/BarChart";
import { XYChart } from "@/components/charts/XYChart";
import { Panel } from "@/components/Panel";
import { Stat } from "@/components/Stat";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { Schemas } from "@/lib/api/client";
import type { EventEffect, IsolationResult } from "@/lib/api/experiments";
import {
  DEMO_SCENARIO,
  useCreateRun,
  useEventLibrary,
  useExperiments,
  useIsolation,
  useRealIsolation,
  useScenarios,
} from "@/lib/api/queries";
import { formatPct, formatSigned, formatSignedPct } from "@/lib/format";
import { cn } from "@/lib/utils";

const PALETTE = [
  "var(--primary)",
  "var(--official)",
  "var(--narrative)",
  "var(--fundamental)",
  "var(--bear)",
  "var(--bull)",
  "var(--reddit)",
  "var(--youtube)",
];
const TPD = 96;
const th = "py-2 text-right font-medium";
const td = "py-2 text-right tabular-nums";
const input =
  "h-8 rounded-md border bg-surface-2 px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/60";
const tabCls =
  "inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/60";

const pct = (x: number | null | undefined, d = 2) => formatSignedPct(x, d);
const hours = (ticks: number | null) => (ticks == null ? "–" : `${(ticks / 4).toFixed(1)} h`);

function Signed({ v, d = 2 }: { v: number; d?: number }) {
  return (
    <span className={cn(v > 0 ? "text-bull-text" : v < 0 ? "text-bear-text" : "")}>
      {formatSignedPct(v, d)}
    </span>
  );
}

/** Effect paths (log-price difference, %) of every event, with the band of the chosen one. */
function EffectChart({
  res,
  label,
  focus,
  height = 300,
}: {
  res: IsolationResult;
  label: string;
  focus: number | null;
  height?: number;
}) {
  const x = res.tick.map((t) => t / TPD);
  const f = res.events.find((e) => e.id === focus);
  return (
    <XYChart
      x={x}
      series={[
        ...res.events.map((e, i) => ({
          key: `e${e.id}`,
          label: e.label.length > 40 ? `${e.label.slice(0, 39)}…` : e.label,
          values: e.path.mean.map((v) => v * 100),
          color: PALETTE[i % PALETTE.length]!,
          width: focus == null || focus === e.id ? 2 : 1,
        })),
        {
          key: "total",
          label: "All events together",
          values: res.total.path.mean.map((v) => v * 100),
          color: "var(--foreground)",
          dash: "4 3",
        },
      ]}
      bands={
        f
          ? [
              {
                key: "band",
                label: "5–95% across seeds",
                lo: f.path.lo.map((v) => v * 100),
                hi: f.path.hi.map((v) => v * 100),
                color: PALETTE[res.events.indexOf(f) % PALETTE.length]!,
                opacity: 0.15,
              },
            ]
          : []
      }
      markers={res.events.map((e, i) => ({
        x: e.tick / TPD,
        label: e.label,
        color: PALETTE[i % PALETTE.length]!,
        tag: String(i + 1),
      }))}
      zeroLine={0}
      height={height}
      xFormat={(d) => `day ${d.toFixed(1)}`}
      yFormat={(v) => `${v.toFixed(1)}%`}
      label={label}
    />
  );
}

function EffectTable({
  events,
  onFocus,
  focus,
  windowEffect = false,
}: {
  events: EventEffect[];
  onFocus: (id: number) => void;
  focus: number | null;
  windowEffect?: boolean;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1000px] text-sm">
        <thead>
          <tr className="border-b text-left text-xs text-muted-foreground">
            <th className="py-2 font-medium">Event</th>
            <th className={th}>True impact</th>
            <th className={th}>{windowEffect ? "Effect over window" : "Isolated effect"}</th>
            <th className={th}>95% CI</th>
            <th className={th}>P(&gt; 0)</th>
            <th className={th}>After 1 day</th>
            <th className={th}>Peak</th>
            <th className={th}>Half of peak</th>
            <th className={th}>Pass-through</th>
            <th className={th}>Extra volume</th>
            <th className={th}>Share of move</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e, i) => (
            <tr
              key={e.id}
              className={cn("border-b last:border-0", focus === e.id && "bg-primary/8")}
            >
              <td className="py-2 pr-3">
                <button
                  type="button"
                  onClick={() => onFocus(e.id)}
                  className="flex items-center gap-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                  aria-pressed={focus === e.id}
                >
                  <span
                    className="inline-flex size-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold text-background"
                    style={{ background: PALETTE[i % PALETTE.length] }}
                    aria-hidden
                  >
                    {i + 1}
                  </span>
                  <span>
                    {e.label}
                    <span className="block text-xs text-muted-foreground">
                      {e.kind} · day {e.day + 1},{" "}
                      {String(Math.floor(((e.tick % TPD) * 15) / 60)).padStart(2, "0")}:
                      {String((e.tick % 4) * 15).padStart(2, "0")} · {e.seeding}
                    </span>
                  </span>
                </button>
              </td>
              <td className={td}>{pct(e.true_impact)}</td>
              <td className={cn(td, "font-medium")}>
                <Signed
                  v={windowEffect && e.window_effect != null ? e.window_effect : e.final.mean}
                />
              </td>
              <td className={cn(td, "text-xs text-muted-foreground")}>
                {pct(e.final.ci95[0])} … {pct(e.final.ci95[1])}
              </td>
              <td className={td}>{formatPct(e.final.p_positive, 0)}</td>
              <td className={td}>{pct(e.one_day.mean)}</td>
              <td className={td}>{pct(e.peak.value)}</td>
              <td className={td}>{hours(e.ticks_to_half_peak)}</td>
              <td className={td}>
                {e.pass_through == null ? "–" : formatSigned(e.pass_through, 2)}
              </td>
              <td className={td}>{formatSignedPct(e.extra_volume, 0)}</td>
              <td className={td}>
                {e.share_of_total == null ? "–" : formatPct(e.share_of_total, 0)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ----------------------------------------------------------------------------- simulator

function SimulatorTab() {
  const scenarios = useScenarios();
  const create = useCreateRun();
  const [source, setSource] = useState("demo");
  const [seeds, setSeeds] = useState(12);
  const [agents, setAgents] = useState(2000);
  const [runId, setRunId] = useState<string | null>(null);
  const [focus, setFocus] = useState<number | null>(null);
  const iso = useIsolation(runId);
  const saved = (scenarios.data ?? []) as Schemas["ScenarioRecord"][];
  const chosen: Schemas["ScenarioSpec"] =
    source === "demo" ? DEMO_SCENARIO : (saved.find((s) => s.id === source)?.spec ?? DEMO_SCENARIO);
  const nEvents = chosen.events?.length ?? 0;
  const status = iso.data?.run.status;
  const last = iso.data?.progress.at(-1);
  const res = iso.data?.result;

  async function start() {
    try {
      const run = await create.mutateAsync({
        mode: "isolation",
        runs: seeds,
        name: `Isolation: ${chosen.name}`,
        scenario: { ...chosen, n_agents: agents },
      } as Schemas["RunCreate"]);
      setRunId(run.id);
      setFocus(null);
      toast.success("Isolation started");
    } catch (e) {
      toast.error(`Could not start: ${String(e)}`);
    }
  }

  return (
    <>
      <Panel
        title="Isolate every event in a scenario"
        icon={Beaker}
        subtitle="Each seed runs the scenario with all events, with none, and once without each event. Same random streams, so the difference is the event's own effect."
      >
        <div className="flex flex-wrap items-end gap-4">
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Scenario
            <select className={input} value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="demo">Demo: rumour → denial → earnings miss</option>
              {saved.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.spec.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Paired seeds
            <input
              className={cn(input, "w-24")}
              type="number"
              min={2}
              max={64}
              value={seeds}
              onChange={(e) => setSeeds(Math.max(2, Math.min(64, Number(e.target.value) || 2)))}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Agents
            <input
              className={cn(input, "w-28")}
              type="number"
              min={500}
              max={20000}
              step={500}
              value={agents}
              onChange={(e) =>
                setAgents(Math.max(500, Math.min(20000, Number(e.target.value) || 500)))
              }
            />
          </label>
          <Button onClick={() => void start()} disabled={create.isPending || nEvents === 0}>
            <Play /> Isolate {nEvents} event{nEvents === 1 ? "" : "s"}
          </Button>
          <p className="text-xs text-muted-foreground">
            {seeds * (nEvents + 2)} simulations of {chosen.days} day{chosen.days === 1 ? "" : "s"}
          </p>
        </div>
        {runId && status !== "done" && (
          <div className="mt-4" role="status" aria-live="polite">
            <p className="text-sm">
              {status === "failed"
                ? `Failed: ${iso.data?.run.error ?? "unknown error"}`
                : `Running… ${last ? `${last.done} of ${last.total} simulations` : "queued"}`}
            </p>
            {last && (
              <div className="mt-2 h-1.5 w-full overflow-hidden rounded bg-surface-2">
                <div
                  className="h-full bg-primary transition-[width]"
                  style={{ width: `${(100 * last.done) / last.total}%` }}
                />
              </div>
            )}
          </div>
        )}
      </Panel>
      {res && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat
              label="Move with all events"
              value={res.total.final.mean * 100}
              format={(v) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}%`}
              hint="vs the same seeds with no events"
            />
            <Stat
              label="Sum of isolated effects"
              value={res.isolated_sum * 100}
              format={(v) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}%`}
            />
            <Stat
              label="Interaction"
              value={res.interaction * 100}
              format={(v) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}%`}
              hint="together minus the sum: events amplify (same sign) or cancel"
            />
            <Stat label="Paired seeds" value={res.seeds} />
          </div>
          <Panel
            title="Isolated price effect of each event"
            icon={Zap}
            subtitle="Mean over seeds of log P(with) − log P(without that event). Click an event in the table for its band."
          >
            <EffectChart
              res={res}
              focus={focus}
              label="Isolated price effect of every event over the run"
            />
          </Panel>
          <Panel
            title="Event by event"
            icon={Layers}
            subtitle="Pass-through: isolated effect / true impact (1 = fully priced, > 1 overreaction)"
          >
            <EffectTable events={res.events} focus={focus} onFocus={setFocus} />
          </Panel>
        </>
      )}
    </>
  );
}

// ----------------------------------------------------------------------------- real moves

function RealTab() {
  const list = useExperiments();
  const ticker = list.data?.[0]?.ticker ?? null;
  const q = useRealIsolation(ticker);
  const [i, setI] = useState(0);
  const [focus, setFocus] = useState<number | null>(null);
  if (q.isLoading || list.isLoading) return <Skeleton className="h-72" />;
  if (!q.data?.windows.length)
    return (
      <EmptyState
        icon={Split}
        title="No real decompositions yet"
        description="Run: uv run python -m marketsim.isolation AAPL"
      />
    );
  const ws = q.data.windows;
  const w = ws[Math.min(i, ws.length - 1)]!;
  const evs = w.events;
  return (
    <>
      <Panel
        title={`${q.data.ticker}: split real earnings moves into each filing's effect`}
        icon={Split}
        subtitle={`Each window is replayed ${q.data.runs}× with its real filings and their measured reactions (fitted agents), once per filing without it`}
        actions={
          <select
            aria-label="Earnings window"
            className={input}
            value={i}
            onChange={(e) => {
              setI(Number(e.target.value));
              setFocus(null);
            }}
          >
            {ws.map((x, k) => (
              <option key={x.origin} value={k}>
                {x.origin} → {x.target}
              </option>
            ))}
          </select>
        }
      >
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat
            label="Real move"
            value={w.real_move * 100}
            format={(v) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}%`}
            hint={`market ${pct(w.market_move)}`}
          />
          <Stat
            label="Real move, market-adjusted"
            value={w.real_abnormal_move * 100}
            format={(v) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}%`}
            hint="what company news has to explain"
          />
          <Stat
            label="Simulated, all filings"
            value={(w.total.window_effect ?? 0) * 100}
            format={(v) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}%`}
          />
          <Stat
            label="Interaction"
            value={w.interaction * 100}
            format={(v) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}%`}
          />
        </div>
        <div className="mt-4">
          <BarChart
            categories={[
              ...evs.map((e, k) => `${k + 1}. ${e.label.split(" (")[0]}`),
              "Interaction",
              "All filings",
              "Real (adjusted)",
            ]}
            groups={[
              {
                key: "effect",
                label: "Effect on the window's move (%)",
                color: "var(--primary)",
                values: [
                  ...evs.map((e) => (e.window_effect ?? e.final.mean) * 100),
                  w.interaction * 100,
                  (w.total.window_effect ?? 0) * 100,
                  w.real_abnormal_move * 100,
                ],
              },
            ]}
            height={240}
            yFormat={(v) => `${v.toFixed(1)}%`}
            label="Each filing's isolated contribution, their interaction, the simulated total and the real market-adjusted move"
          />
        </div>
      </Panel>
      <Panel
        title="Effect paths"
        icon={Zap}
        subtitle={`Replay from ${w.start}; the forecast window starts at the close of ${w.origin}`}
      >
        <EffectChart
          res={w}
          focus={focus}
          height={260}
          label="Isolated effect of each real filing over the replay"
        />
      </Panel>
      <Panel
        title="Filings in the window"
        icon={Layers}
        subtitle="Effect over window: from the close before the release to the end of the window"
      >
        <EffectTable events={evs} focus={focus} onFocus={setFocus} windowEffect />
      </Panel>
    </>
  );
}

// ----------------------------------------------------------------------------- library

function LibraryTab() {
  const q = useEventLibrary();
  const lib = q.data;
  const cat = useMemo(() => lib?.catalog ?? [], [lib]);
  if (q.isLoading) return <Skeleton className="h-72" />;
  if (!lib)
    return (
      <EmptyState
        icon={Library}
        title="No event library yet"
        description="Run: uv run python scripts/fetch_market_data.py, then uv run python -m marketsim.event_library"
      />
    );
  const p = lib.model.pooled;
  const o = lib.model.own_vs_pooled;
  return (
    <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label="Events"
          value={lib.n_events}
          hint={`${lib.tickers.length} stocks, SEC filings since 2015`}
        />
        <Stat
          label="Size prediction"
          value={p.size_corr}
          format={(v) => v.toFixed(2)}
          hint="corr. of predicted and actual |reaction|, out of sample"
        />
        <Stat
          label="Direction on real moves"
          value={p.direction_hit_rate * 100}
          format={(v) => `${v.toFixed(0)}%`}
          hint={`of ${p.n_moves} moves beyond ±1%`}
        />
        <Stat
          label="Pooled vs own-stock model"
          value={o ? o.size_corr_pooled : null}
          format={(v) => v.toFixed(2)}
          hint={o ? `own-stock: ${o.size_corr_own.toFixed(2)} (n=${o.n})` : "–"}
        />
      </div>
      <Panel
        title="Isolated real effect of each event type"
        icon={FlaskConical}
        subtitle="Abnormal return vs SPY on the reaction day · |SAR| 1 = as big as an ordinary day · excess: beyond a normal day's abnormal move"
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="py-2 font-medium">Event type</th>
                <th className={th}>Events</th>
                <th className={th}>Stocks</th>
                <th className={th}>|SAR|</th>
                <th className={th}>Mean |AR|</th>
                <th className={th}>Normal day</th>
                <th className={th}>Excess</th>
                <th className={th}>Mean AR (t)</th>
                <th className={th}>Share up</th>
                <th className={th}>Moves &gt; 3 sd</th>
                <th className={th}>Day 0 share of 5-day</th>
                <th className={th}>Volume ×</th>
              </tr>
            </thead>
            <tbody>
              {cat.map((c) => (
                <tr key={c.group} className="border-b last:border-0">
                  <td className="py-2">{c.group.replace("_", " ")}</td>
                  <td className={td}>{c.n.toLocaleString()}</td>
                  <td className={td}>{c.tickers}</td>
                  <td className={cn(td, "font-medium")}>{c.abs_sar.toFixed(2)}</td>
                  <td className={td}>{formatPct(c.mean_abs_ar, 2)}</td>
                  <td className={td}>{formatPct(c.normal_abs_ar, 2)}</td>
                  <td className={td}>
                    <Signed v={c.excess_abs_ar} />
                  </td>
                  <td className={td}>
                    {pct(c.mean_ar)}{" "}
                    <span className="text-xs text-muted-foreground">
                      ({formatSigned(c.t_direction, 1)})
                    </span>
                  </td>
                  <td className={td}>{formatPct(c.share_up, 0)}</td>
                  <td className={td}>{formatPct(c.share_big, 0)}</td>
                  <td className={td}>{formatPct(c.day0_share_of_5d, 0)}</td>
                  <td className={td}>{c.volume_ratio_median.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-4">
          <BarChart
            categories={cat.map((c) => c.group.replace("_", " "))}
            groups={[
              {
                key: "sar",
                label: "|SAR| (1 = normal day)",
                color: "var(--primary)",
                values: cat.map((c) => c.abs_sar),
              },
            ]}
            height={220}
            yFormat={(v) => v.toFixed(1)}
            label="Size of each event type's reaction in units of a normal day"
          />
        </div>
      </Panel>
      <Panel
        title="How fast each event type is priced in"
        icon={Zap}
        subtitle="Mean |cumulative abnormal return| from the reaction day to 5 days after"
      >
        <XYChart
          x={[0, 1, 2, 3, 4, 5]}
          series={cat.slice(0, 5).map((c, i) => ({
            key: c.group,
            label: c.group.replace("_", " "),
            values: c.car_abs_mean.map((v) => v * 100),
            color: PALETTE[i % PALETTE.length]!,
          }))}
          height={240}
          xTicks={[0, 1, 2, 3, 4, 5]}
          xFormat={(d) => `day ${Math.round(d)}`}
          yFormat={(v) => `${v.toFixed(1)}%`}
          label="Mean absolute cumulative abnormal return over the five days after each event type"
        />
      </Panel>
      <Panel
        title="Earnings reactions by stock"
        icon={Boxes}
        subtitle="How many normal days an earnings day is worth, per company"
      >
        <div
          className="max-h-[420px] overflow-auto rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          tabIndex={0}
          role="region"
          aria-label="Earnings reactions by stock"
        >
          <table className="w-full min-w-[640px] text-sm">
            <thead className="sticky top-0 bg-card">
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="py-2 font-medium">Stock</th>
                <th className={th}>Releases</th>
                <th className={th}>|SAR|</th>
                <th className={th}>Mean |AR|</th>
                <th className={th}>Share up</th>
                <th className={th}>Largest</th>
              </tr>
            </thead>
            <tbody>
              {lib.earnings_by_ticker.map((r) => (
                <tr key={r.ticker} className="border-b last:border-0">
                  <td className="py-2">
                    <span className="font-mono text-xs">{r.ticker}</span>{" "}
                    <span className="text-muted-foreground">{r.name}</span>
                  </td>
                  <td className={td}>{r.n}</td>
                  <td className={cn(td, "font-medium")}>{r.abs_sar.toFixed(2)}</td>
                  <td className={td}>{formatPct(r.mean_abs_ar, 2)}</td>
                  <td className={td}>{formatPct(r.share_up, 0)}</td>
                  <td className={td}>
                    <Signed v={r.largest} d={1} />
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

export function EventLabPage() {
  const [tab, setTab] = useState<"sim" | "real" | "lib">("sim");
  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-5 p-6">
      <div>
        <p className="font-mono text-[11px] tracking-[0.16em] text-primary">EVENT LAB</p>
        <h2 className="mt-1 text-2xl font-semibold tracking-tight">
          What did each event do to the price?
        </h2>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Isolate the effect of individual events: paired counterfactual simulations (with and
          without each event, same random streams), real earnings moves split into each
          filing&apos;s contribution, and the measured effect of every event type across thousands
          of real filings.
        </p>
      </div>
      <div
        className="flex gap-1 rounded-lg border bg-card p-1"
        role="tablist"
        aria-label="Event lab"
      >
        {(
          [
            ["sim", "Simulator", Beaker],
            ["real", "Real earnings moves", Split],
            ["lib", "Event library", Library],
          ] as const
        ).map(([k, label, Icon]) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={cn(
              tabCls,
              tab === k
                ? "bg-primary/12 font-medium"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="size-4" aria-hidden />
            {label}
          </button>
        ))}
      </div>
      {tab === "sim" ? <SimulatorTab /> : tab === "real" ? <RealTab /> : <LibraryTab />}
    </div>
  );
}
