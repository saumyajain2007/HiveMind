import {
  CircleCheck,
  CircleX,
  Crosshair,
  Database,
  FlaskConical,
  Play,
  Target,
  TrendingDown,
  TrendingUp,
  Upload,
} from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { BarChart } from "@/components/charts/BarChart";
import { ScatterChart } from "@/components/charts/ScatterChart";
import { XYChart } from "@/components/charts/XYChart";
import { Panel } from "@/components/Panel";
import { Stat } from "@/components/Stat";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { Schemas } from "@/lib/api/client";
import {
  useBacktest,
  useCalibration,
  useCreateBacktest,
  useCreateCalibration,
  useDatasets,
  useRuns,
  useUploadDataset,
} from "@/lib/api/queries";
import { formatPrice, formatRelative, formatSigned } from "@/lib/format";
import { cn } from "@/lib/utils";

const input =
  "h-8 rounded-md border bg-surface-2 px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/60";

const PARAMS: { key: string; label: string; lo: number; hi: number }[] = [
  { key: "impact_Y", label: "impact_Y (market depth)", lo: 0.3, hi: 1.5 },
  { key: "base_share", label: "base_share (sharing)", lo: 0.1, hi: 0.5 },
  { key: "mu0", label: "mu0 (belief step)", lo: 0.1, hi: 0.7 },
  { key: "sentiment_scale", label: "sentiment_scale", lo: 0.01, hi: 0.1 },
];

/** From `python -m marketsim.calibration` (DECISIONS.md, parameter-recovery test, #12). */
const RECOVERY = [
  { p: "impact_Y", truth: 0.9, one: 1.33, eight: 0.701, corr: 0.39 },
  { p: "base_share", truth: 0.3, one: 0.125, eight: 0.348, corr: 0.13 },
  { p: "mu0", truth: 0.4, one: 0.39, eight: 0.145, corr: -0.09 },
  { p: "sentiment_scale", truth: 0.055, one: 0.0843, eight: 0.033, corr: 0.08 },
];

function readFile(f: File): Promise<string> {
  return f.text();
}

function DatasetPicker({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (id: string) => void;
}) {
  const datasets = useDatasets();
  const upload = useUploadDataset();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [csv, setCsv] = useState<File | null>(null);
  const [events, setEvents] = useState<File | null>(null);
  const list = datasets.data ?? [];
  const current = value ?? list[0]?.id ?? null;
  async function submit() {
    if (!csv) return;
    try {
      const body: Schemas["DatasetUpload"] = {
        name: name || csv.name.replace(/\.csv$/i, ""),
        csv: await readFile(csv),
        events: events
          ? (JSON.parse(await readFile(events)) as Schemas["DatasetUpload"]["events"])
          : [],
      };
      const rec = await upload.mutateAsync(body);
      onChange(rec.id);
      setOpen(false);
      toast.success(`Uploaded “${rec.name}”`, {
        description: `${rec.n_days} days, ${rec.n_events} events`,
      });
    } catch (e) {
      toast.error("Upload rejected", { description: (e as Error).message });
    }
  }
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Dataset
          <select
            className={cn(input, "min-w-64")}
            value={current ?? ""}
            onChange={(e) => onChange(e.target.value)}
          >
            {!list.length && <option value="">No datasets yet</option>}
            {list.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name} · {d.n_days} days · {d.n_events} events
              </option>
            ))}
          </select>
        </label>
        <Button variant="outline" size="sm" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          <Upload />
          Upload data
        </Button>
      </div>
      {open && (
        <div className="grid gap-2 rounded-lg border bg-surface-2/50 p-3 sm:grid-cols-3">
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Name
            <input
              className={input}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="ACME 2024"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Prices (CSV: date,close)
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => setCsv(e.target.files?.[0] ?? null)}
              className="text-xs"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Events (JSON, optional)
            <input
              type="file"
              accept=".json,application/json"
              onChange={(e) => setEvents(e.target.files?.[0] ?? null)}
              className="text-xs"
            />
          </label>
          <p className="text-[11px] text-muted-foreground sm:col-span-2">
            Events use the scenario format with <code className="font-mono">date</code> (or{" "}
            <code className="font-mono">day</code>) and optional{" "}
            <code className="font-mono">time</code> instead of{" "}
            <code className="font-mono">tick</code>.
          </p>
          <Button
            size="sm"
            onClick={() => void submit()}
            disabled={!csv || upload.isPending}
            className="justify-self-end"
          >
            Upload
          </Button>
        </div>
      )}
    </div>
  );
}

function useAnalysisRuns(mode: "calibration" | "backtest") {
  const runs = useRuns();
  return (runs.data?.items ?? []).filter((r) => r.mode === mode);
}

function RunSelect({
  runs,
  value,
  onChange,
}: {
  runs: Schemas["RunRecord"][];
  value: string | null;
  onChange: (id: string) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-xs text-muted-foreground">
      Result
      <select
        className={cn(input, "max-w-80")}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
      >
        {!runs.length && <option value="">None yet</option>}
        {runs.map((r) => (
          <option key={r.id} value={r.id}>
            {r.name} · {r.status} · {formatRelative(r.created_at)}
          </option>
        ))}
      </select>
    </label>
  );
}

// ----------------------------------------------------------------------------- calibration

function CalibrationTab() {
  const [dataset, setDataset] = useState<string | null>(null);
  const datasets = useDatasets();
  const runs = useAnalysisRuns("calibration");
  const [picked, setPicked] = useState<string | null>(null);
  const id = picked ?? runs[0]?.id ?? null;
  const cal = useCalibration(id);
  const create = useCreateCalibration();
  const [on, setOn] = useState<Record<string, boolean>>(
    Object.fromEntries(PARAMS.map((p) => [p.key, true])),
  );
  const [range, setRange] = useState<Record<string, [number, number]>>(
    Object.fromEntries(PARAMS.map((p) => [p.key, [p.lo, p.hi]])),
  );
  const [trials, setTrials] = useState(40);
  const [perTrial, setPerTrial] = useState(4);
  const [agents, setAgents] = useState(3000);
  const ds = dataset ?? datasets.data?.[0]?.id ?? null;
  const bad = PARAMS.filter((p) => on[p.key] && !(range[p.key]![0] <= range[p.key]![1]));

  async function start() {
    if (!ds) return;
    try {
      const space = Object.fromEntries(
        PARAMS.filter((p) => on[p.key]).map((p) => [p.key, range[p.key]!]),
      );
      const r = await create.mutateAsync({
        dataset_id: ds,
        space,
        n_trials: trials,
        runs_per_trial: perTrial,
        n_agents: agents,
        seed: 0,
      });
      setPicked(r.id);
      toast.success("Calibration started", { description: `${trials} trials × ${perTrial} runs` });
    } catch (e) {
      toast.error("Could not start", { description: (e as Error).message });
    }
  }

  const res = cal.data?.result;
  const trialLog = res?.trials ?? cal.data?.progress ?? [];
  const best = res
    ? res.best_rmse
    : trialLog.length
      ? Math.min(...trialLog.map((t) => t.rmse))
      : null;
  const params = Object.keys(res?.space ?? trialLog[0]?.params ?? {});
  return (
    <div className="flex flex-col gap-5">
      <Panel
        title="New calibration"
        icon={FlaskConical}
        subtitle="Random search, minimising RMSE between the median simulated and the observed log price (both measured from day 1)"
      >
        <div className="flex flex-col gap-4">
          <DatasetPicker value={ds} onChange={setDataset} />
          <fieldset className="grid gap-2 sm:grid-cols-2">
            <legend className="mb-1 text-xs font-medium text-muted-foreground">
              Parameters and search ranges
            </legend>
            {PARAMS.map((p) => (
              <div key={p.key} className="flex items-center gap-2 rounded-md border px-2 py-1.5">
                <input
                  type="checkbox"
                  checked={on[p.key]}
                  onChange={(e) => setOn({ ...on, [p.key]: e.target.checked })}
                  aria-label={`Fit ${p.key}`}
                />
                <span className="flex-1 truncate font-mono text-xs">{p.label}</span>
                {(["low", "high"] as const).map((side, j) => (
                  <input
                    key={side}
                    type="number"
                    step="any"
                    aria-label={`${p.key} ${side}`}
                    aria-invalid={bad.includes(p) ? true : undefined}
                    disabled={!on[p.key]}
                    className={cn(
                      input,
                      "tabular h-7 w-20 font-mono text-xs aria-[invalid]:border-destructive",
                    )}
                    value={range[p.key]![j]}
                    onChange={(e) => {
                      const next = [...range[p.key]!] as [number, number];
                      next[j] = Number(e.target.value);
                      setRange({ ...range, [p.key]: next });
                    }}
                  />
                ))}
              </div>
            ))}
          </fieldset>
          {bad.length > 0 && (
            <p role="alert" className="text-xs text-bear-text">
              {bad.map((b) => b.key).join(", ")}: the low end must not exceed the high end.
            </p>
          )}
          <div className="flex flex-wrap items-end gap-3">
            {[
              ["Trials", trials, setTrials, 1, 1000],
              ["Runs per trial", perTrial, setPerTrial, 1, 50],
              ["Agents", agents, setAgents, 100, 200000],
            ].map(([label, v, set, lo, hi]) => (
              <label
                key={label as string}
                className="flex flex-col gap-1 text-xs text-muted-foreground"
              >
                {label as string}
                <input
                  type="number"
                  className={cn(input, "tabular w-28 font-mono")}
                  value={v as number}
                  min={lo as number}
                  max={hi as number}
                  onChange={(e) =>
                    (set as (n: number) => void)(
                      Math.max(
                        lo as number,
                        Math.min(hi as number, Number(e.target.value) || (lo as number)),
                      ),
                    )
                  }
                />
              </label>
            ))}
            <Button
              onClick={() => void start()}
              disabled={
                !ds || bad.length > 0 || !Object.values(on).some(Boolean) || create.isPending
              }
            >
              <Play />
              Start calibration
            </Button>
          </div>
        </div>
      </Panel>

      <div className="flex justify-end">
        <RunSelect runs={runs} value={id} onChange={setPicked} />
      </div>
      {!id ? null : !cal.data ? (
        <Skeleton className="h-64" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Stat label="Trials" value={trialLog.length} hint={cal.data.run.status} />
            <Stat label="Best RMSE" value={best} format={(v) => v.toFixed(4)} hint="log price" />
            {res &&
              Object.entries(res.best)
                .slice(0, 2)
                .map(([k, v]) => (
                  <Stat
                    key={k}
                    label={`Best ${k}`}
                    value={v}
                    format={(x) => x.toPrecision(3)}
                    hint={`sensitivity ${formatSigned(res.sensitivity[k] ?? 0)}`}
                  />
                ))}
          </div>
          <Panel
            title="Trial log"
            icon={Crosshair}
            subtitle="Each trial's parameter value against its RMSE · large point: best trial"
          >
            <div className="grid gap-4 md:grid-cols-2">
              {params.map((p) => (
                <ScatterChart
                  key={p}
                  points={trialLog.map((t) => ({
                    x: t.params[p]!,
                    y: t.rmse,
                    label: `trial ${t.trial}: ${p} ${t.params[p]!.toPrecision(3)}, RMSE ${t.rmse.toFixed(4)}`,
                    highlight: t.rmse === best,
                  }))}
                  xLabel={p}
                  yLabel="RMSE"
                  label={`RMSE against ${p}`}
                  height={180}
                />
              ))}
            </div>
          </Panel>
          {res && (
            <Panel
              title="Best fit"
              icon={Target}
              subtitle="Observed vs the median simulated path at the best parameters (log price relative to day 1)"
            >
              <XYChart
                x={res.observed.map((_, i) => i)}
                series={[
                  {
                    key: "obs",
                    label: "Observed",
                    values: res.observed,
                    color: "var(--foreground)",
                  },
                  {
                    key: "fit",
                    label: "Best fit (median of runs)",
                    values: res.best_path,
                    color: "var(--bull)",
                    dash: "6 3",
                  },
                ]}
                height={260}
                zeroLine={0}
                xFormat={(i) => res.dates[Math.round(i)] ?? `day ${Math.round(i)}`}
                yFormat={(v) => `${(v * 100).toFixed(1)}%`}
                label="Observed and best-fit log price"
              />
            </Panel>
          )}
        </>
      )}

      <Panel
        title="Parameter-recovery test"
        icon={CircleCheck}
        subtitle="Synthetic data from known parameters, then calibrated (python -m marketsim.calibration; 5,000 agents, 5 days, 40 trials × 4 runs)"
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="py-2 font-medium">Parameter</th>
                <th className="py-2 text-right font-medium">True</th>
                <th className="py-2 text-right font-medium">Recovered (one path)</th>
                <th className="py-2 text-right font-medium">Recovered (median of 8)</th>
                <th className="py-2 text-right font-medium">Rank corr. with RMSE</th>
                <th className="py-2 pl-4 font-medium">Verdict</th>
              </tr>
            </thead>
            <tbody>
              {RECOVERY.map((r) => {
                const ok = Math.abs(r.eight - r.truth) / r.truth < 0.15;
                return (
                  <tr key={r.p} className="border-b last:border-0">
                    <td className="py-2 font-mono">{r.p}</td>
                    <td className="tabular py-2 text-right font-mono">{r.truth}</td>
                    <td className="tabular py-2 text-right font-mono">{r.one}</td>
                    <td className="tabular py-2 text-right font-mono">{r.eight}</td>
                    <td className="tabular py-2 text-right font-mono">{formatSigned(r.corr)}</td>
                    <td className="py-2 pl-4">
                      <span
                        className={cn(
                          "inline-flex items-center gap-1 text-xs",
                          ok ? "text-status-good-text" : "text-bear-text",
                        )}
                      >
                        {ok ? (
                          <CircleCheck className="size-3.5" aria-hidden />
                        ) : (
                          <CircleX className="size-3.5" aria-hidden />
                        )}
                        {ok
                          ? "recovered"
                          : Math.abs(r.corr) < 0.2
                            ? "weakly identified"
                            : "not recovered"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          One 5-day path does not identify these parameters: the search fits the noise of the path
          better than the truth does. See DECISIONS.md for the full tables.
        </p>
      </Panel>
    </div>
  );
}

// ----------------------------------------------------------------------------- backtest

function BacktestTab() {
  const [dataset, setDataset] = useState<string | null>(null);
  const datasets = useDatasets();
  const runs = useAnalysisRuns("backtest");
  const [picked, setPicked] = useState<string | null>(null);
  const id = picked ?? runs[0]?.id ?? null;
  const bt = useBacktest(id);
  const create = useCreateBacktest();
  const [horizon, setHorizon] = useState(1);
  const [nRuns, setNRuns] = useState(10);
  const [from, setFrom] = useState(20);
  const [step, setStep] = useState(1);
  const ds = dataset ?? datasets.data?.[0]?.id ?? null;
  const nDays = datasets.data?.find((d) => d.id === ds)?.n_days ?? 0;

  async function start() {
    if (!ds) return;
    const origins: number[] = [];
    for (let o = from; o < nDays - horizon; o += step) origins.push(o);
    if (!origins.length) {
      toast.error("No origins", {
        description: `The dataset has ${nDays} days; start earlier or shorten the horizon.`,
      });
      return;
    }
    try {
      const r = await create.mutateAsync({
        dataset_id: ds,
        origins,
        horizon,
        runs: nRuns,
        n_agents: 2000,
        seed: 0,
        lookback_days: 3,
      });
      setPicked(r.id);
      toast.success("Backtest started", { description: `${origins.length} origins` });
    } catch (e) {
      toast.error("Could not start", { description: (e as Error).message });
    }
  }

  const res = bt.data?.result;
  const rows = res?.origins ?? bt.data?.progress ?? [];
  const skill = res?.skill ?? null;
  const chart = useMemo(() => {
    if (!res) return null;
    const x = res.closes.map((_, i) => i);
    return { x };
  }, [res]);
  return (
    <div className="flex flex-col gap-5">
      <Panel
        title="New backtest"
        icon={Target}
        subtitle="For each origin: events up to the origin only, Monte Carlo forward, CRPS of the model and of a random walk"
      >
        <div className="flex flex-col gap-4">
          <DatasetPicker value={ds} onChange={setDataset} />
          <div className="flex flex-wrap items-end gap-3">
            {[
              ["Horizon (days)", horizon, setHorizon, 1, 60],
              ["Runs per origin", nRuns, setNRuns, 1, 200],
              ["First origin (day)", from, setFrom, 0, 10000],
              ["Every n days", step, setStep, 1, 100],
            ].map(([label, v, set, lo, hi]) => (
              <label
                key={label as string}
                className="flex flex-col gap-1 text-xs text-muted-foreground"
              >
                {label as string}
                <input
                  type="number"
                  className={cn(input, "tabular w-28 font-mono")}
                  value={v as number}
                  min={lo as number}
                  max={hi as number}
                  onChange={(e) =>
                    (set as (n: number) => void)(
                      Math.max(
                        lo as number,
                        Math.min(hi as number, Number(e.target.value) || (lo as number)),
                      ),
                    )
                  }
                />
              </label>
            ))}
            <Button onClick={() => void start()} disabled={!ds || create.isPending}>
              <Play />
              Start backtest
            </Button>
          </div>
        </div>
      </Panel>
      <div className="flex justify-end">
        <RunSelect runs={runs} value={id} onChange={setPicked} />
      </div>
      {!id ? null : !bt.data ? (
        <Skeleton className="h-64" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <div
              className={cn(
                "rounded-xl border p-4",
                skill == null
                  ? "bg-card"
                  : skill > 0
                    ? "border-bull/40 bg-bull/[0.06]"
                    : "border-bear/40 bg-bear/[0.06]",
              )}
            >
              <p className="text-xs text-muted-foreground">CRPS skill vs random walk</p>
              <p
                className={cn(
                  "tabular mt-2 flex items-center gap-2 font-mono text-2xl font-semibold",
                  skill == null ? "" : skill > 0 ? "text-bull-text" : "text-bear-text",
                )}
              >
                {skill == null ? (
                  "–"
                ) : skill > 0 ? (
                  <TrendingUp className="size-5" aria-hidden />
                ) : (
                  <TrendingDown className="size-5" aria-hidden />
                )}
                {skill == null ? "" : formatSigned(skill, 3)}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {skill == null
                  ? "running"
                  : skill > 0
                    ? "beats the random walk"
                    : "worse than the random walk"}
              </p>
            </div>
            <Stat
              label="Mean CRPS, model"
              value={res?.mean_crps_model}
              format={(v) => v.toFixed(3)}
              hint="lower is better"
            />
            <Stat
              label="Mean CRPS, random walk"
              value={res?.mean_crps_rw}
              format={(v) => v.toFixed(3)}
              hint="same trailing vol"
            />
            <Stat
              label="Origins"
              value={rows.length}
              hint={res ? `horizon ${res.horizon} day${res.horizon === 1 ? "" : "s"}` : "so far"}
            />
          </div>
          {res && chart && (
            <Panel
              title="Origins on the price"
              icon={Target}
              subtitle="Close price · whiskers: model 5–95% forecast at origin + horizon · dot: actual"
            >
              <XYChart
                x={chart.x}
                series={[
                  {
                    key: "close",
                    label: "Close",
                    values: res.closes,
                    color: "var(--foreground)",
                    width: 1.5,
                  },
                ]}
                height={280}
                xFormat={(i) => res.dates[Math.round(i)] ?? String(i)}
                yFormat={(v) => formatPrice(v)}
                yDomain={[
                  Math.min(...res.closes, ...res.origins.map((o) => o.model_q05)) * 0.99,
                  Math.max(...res.closes, ...res.origins.map((o) => o.model_q95)) * 1.01,
                ]}
                label="Close price with forecast intervals at each origin"
                legend={false}
                overlay={(sx, sy) =>
                  res.origins.map((o) => {
                    const x = sx(o.origin + res.horizon);
                    return (
                      <g key={o.origin}>
                        <line
                          x1={x}
                          x2={x}
                          y1={sy(o.model_q05)}
                          y2={sy(o.model_q95)}
                          stroke="var(--bull)"
                          strokeWidth={3}
                          strokeLinecap="round"
                          opacity={0.7}
                        />
                        <circle
                          cx={x}
                          cy={sy(o.actual)}
                          r={4}
                          fill={o.crps_model < o.crps_rw ? "var(--bull)" : "var(--bear)"}
                          stroke="var(--card)"
                          strokeWidth={2}
                        >
                          <title>{`${o.date ?? o.origin}: actual ${formatPrice(o.actual)}, model ${formatPrice(o.model_q05)}–${formatPrice(o.model_q95)}`}</title>
                        </circle>
                      </g>
                    );
                  })
                }
              />
            </Panel>
          )}
          <Panel title="CRPS per origin" icon={Target} subtitle="Lower is better">
            <BarChart
              categories={rows.map((o) => (o.date ? o.date.slice(5) : String(o.origin)))}
              groups={[
                {
                  key: "model",
                  label: "Model",
                  color: "var(--bull)",
                  values: rows.map((o) => o.crps_model),
                },
                {
                  key: "rw",
                  label: "Random walk",
                  color: "var(--muted-foreground)",
                  values: rows.map((o) => o.crps_rw),
                },
              ]}
              height={260}
              yFormat={(v) => v.toFixed(2)}
              label="CRPS of the model and the random walk at each origin"
            />
          </Panel>
        </>
      )}
    </div>
  );
}

export function AnalysisPage() {
  const [tab, setTab] = useState<"cal" | "bt">("cal");
  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-5 p-6">
      <div>
        <p className="font-mono text-[11px] tracking-[0.16em] text-primary">ANALYSIS</p>
        <h2 className="mt-1 text-2xl font-semibold tracking-tight">Calibration and backtests</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Fit the model to a real price series, and check its forecasts against a random walk.{" "}
        </p>
      </div>
      <div
        className="flex gap-1 rounded-lg border bg-card p-1"
        role="tablist"
        aria-label="Analysis"
      >
        {(
          [
            ["cal", "Calibration", FlaskConical],
            ["bt", "Backtest", Database],
          ] as const
        ).map(([k, label, Icon]) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={cn(
              "inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
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
      {tab === "cal" ? <CalibrationTab /> : <BacktestTab />}
    </div>
  );
}
