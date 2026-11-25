import {
  ChartSpline,
  CircleAlert,
  FileDiff,
  Play,
  Plus,
  RotateCcw,
  Save,
  ScrollText,
  Shuffle,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";

import { Panel } from "@/components/Panel";
import { Tag } from "@/components/badges";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EventEditor } from "@/features/builder/EventEditor";
import { branchingRatio, DEFAULT_HAWKES, hawkesEvents } from "@/features/builder/hawkes";
import type { HawkesParams } from "@/features/builder/hawkes";
import { ImportHeadlines } from "@/features/builder/ImportHeadlines";
import { parameterDiff, same } from "@/features/builder/diff";
import { ParameterPanel } from "@/features/builder/ParameterPanel";
import { newEvent, PRESETS } from "@/features/builder/presets";
import { builderStore, nextEventId, useBuilder, validateScenario } from "@/features/builder/store";
import type { Parameters } from "@/features/builder/store";
import { Timeline } from "@/features/builder/Timeline";
import type { Schemas } from "@/lib/api/client";
import {
  useConfigDefaults,
  useConfigSchema,
  useCreateRun,
  useSaveScenario,
  useScenarios,
} from "@/lib/api/queries";
import { formatCompact, simClock, TICKS_PER_DAY } from "@/lib/format";
import { connectRun } from "@/lib/live/store";
import { cn } from "@/lib/utils";

const FALLBACK_ENUMS: Schemas["Enumerations"] = {
  kinds: ["earnings", "macro", "regulatory", "product", "rumour", "leak", "statement"],
  seedings: ["official", "outlet", "influencer", "insider", "anonymous"],
  topics: ["finance"],
  platforms: [],
  categories: [],
};

const input =
  "h-8 rounded-md border bg-surface-2 px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/60 aria-[invalid]:border-destructive";

function HawkesForm({ onDone }: { onDone: () => void }) {
  const days = useBuilder((s) => s.scenario.days ?? 5);
  const events = useBuilder((s) => s.scenario.events);
  const [p, setP] = useState<HawkesParams>(DEFAULT_HAWKES);
  const preview = useMemo(
    () => hawkesEvents(p, days * TICKS_PER_DAY, nextEventId(events)),
    [p, days, events],
  );
  const n = branchingRatio(p);
  const num = (k: keyof HawkesParams, label: string, step: number, min: number, max: number) => (
    <label className="flex flex-col gap-1 text-xs text-muted-foreground">
      {label}
      <input
        type="number"
        className={cn(input, "tabular font-mono")}
        step={step}
        min={min}
        max={max}
        value={p[k]}
        onChange={(e) =>
          setP({ ...p, [k]: Math.max(min, Math.min(max, Number(e.target.value) || 0)) })
        }
      />
    </label>
  );
  return (
    <div className="flex flex-col gap-3 rounded-lg border bg-surface-2/60 p-3">
      <p className="text-xs text-muted-foreground">
        Self-exciting shocks: each event makes more events likely soon after (a Hawkes process).
      </p>
      <div className="grid grid-cols-5 gap-2">
        {num("mu", "Base rate μ / tick", 0.001, 0, 1)}
        {num("alpha", "Excitation α", 0.05, 0, 5)}
        {num("beta", "Decay β", 0.05, 0.01, 10)}
        {num("impactSd", "Impact sd", 0.005, 0, 0.3)}
        {num("seed", "Seed", 1, 0, 1e9)}
      </div>
      <p className={cn("text-xs", n >= 1 ? "text-bear-text" : "text-muted-foreground")}>
        Branching ratio {n.toFixed(2)}
        {n >= 1 ? " (explosive: lower α or raise β)" : ""} · {preview.length} events over {days}{" "}
        days
      </p>
      <div className="flex gap-2">
        <Button
          size="sm"
          disabled={!preview.length || n >= 1}
          onClick={() => {
            builderStore.getState().addEvents(preview);
            toast.success(`Added ${preview.length} random shocks`);
            onDone();
          }}
        >
          <Shuffle />
          Add {preview.length} shocks
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function DiffView({ schema }: { schema: Schemas["ConfigSchema"] }) {
  const params = useBuilder((s) => s.parameters);
  const rows = parameterDiff(schema, params);
  if (!rows.length)
    return <p className="text-sm text-muted-foreground">Every parameter is at its default.</p>;
  const show = (v: unknown) =>
    typeof v === "number" ? String(Number(v.toPrecision(4))) : JSON.stringify(v);
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-left text-muted-foreground">
          <th className="py-1 font-medium">Parameter</th>
          <th className="py-1 font-medium">Default</th>
          <th className="py-1 font-medium">This scenario</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.key} className="border-t">
            <td className="py-1.5 font-mono">{r.key}</td>
            <td className="max-w-40 truncate py-1.5 font-mono text-muted-foreground">
              {show(r.from)}
            </td>
            <td className="max-w-40 truncate py-1.5 font-mono text-primary">{show(r.to)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function BuilderPage() {
  const schema = useConfigSchema();
  const defaults = useConfigDefaults();
  const scenarios = useScenarios();
  const save = useSaveScenario();
  const create = useCreateRun();
  const navigate = useNavigate();
  const scenario = useBuilder((s) => s.scenario);
  const parameters = useBuilder((s) => s.parameters);
  const scenarioId = useBuilder((s) => s.scenarioId);
  const [importOpen, setImportOpen] = useState(false);
  const [hawkes, setHawkes] = useState(false);
  const [showDiff, setShowDiff] = useState(false);
  const [mcRuns, setMcRuns] = useState(20);
  const st = builderStore.getState;

  useEffect(() => {
    if (!defaults.data) return;
    const d = defaults.data.parameters as unknown as Parameters;
    const s = st();
    if (!s.parameters) s.setParameters(d);
    else if (!s.pinned && !same(s.base, d)) {
      // saved parameters predate the current engine defaults: follow them, keep the user's edits
      s.rebase(d);
      toast.info("Parameters updated to the engine's current defaults", {
        description: "Settings you changed yourself are kept.",
      });
    }
  }, [parameters, defaults.data, st]);

  const issues = useMemo(() => validateScenario(scenario), [scenario]);
  const fieldIssue = (k: string) => issues.find((i) => i.where === k)?.message;
  const events = scenario.events ?? [];
  const ready = issues.length === 0 && Boolean(parameters);

  async function run(mode: "single" | "montecarlo") {
    if (!ready) return;
    try {
      const r = await create.mutateAsync({
        scenario,
        parameters: parameters!,
        mode,
        runs: mode === "single" ? 1 : mcRuns,
        workers: mode === "single" ? 1 : 2,
        pace: mode === "single" ? 48 : 0,
      });
      if (mode === "single") {
        connectRun(r.id);
        navigate("/cockpit");
      } else navigate(`/monte-carlo?run=${r.id}`);
      toast.success(mode === "single" ? "Live run started" : `Monte Carlo ×${mcRuns} started`, {
        description: `${r.name} · ${r.id}`,
      });
    } catch (e) {
      toast.error("The API rejected the run", { description: (e as Error).message });
    }
  }

  async function saveScenario() {
    try {
      const rec = await save.mutateAsync({ id: scenarioId, spec: scenario });
      st().load(rec.spec, rec.id);
      toast.success(scenarioId ? "Scenario updated" : "Scenario saved");
    } catch (e) {
      toast.error("Could not save", { description: (e as Error).message });
    }
  }

  return (
    <div className="mx-auto flex max-w-[1500px] flex-col gap-5 p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-mono text-[11px] tracking-[0.16em] text-primary">SCENARIO BUILDER</p>
          <h2 className="mt-1 text-2xl font-semibold tracking-tight">
            {scenario.name || "Untitled scenario"}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {formatCompact(scenario.n_agents ?? 0)} agents · {scenario.days} days · {events.length}{" "}
            event
            {events.length === 1 ? "" : "s"}
            {scenarioId ? ` · saved as ${scenarioId}` : " · not saved"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label="Load a preset or saved scenario"
            className={input}
            value=""
            onChange={(e) => {
              const v = e.target.value;
              const preset = PRESETS.find((p) => p.key === v);
              if (preset) st().load(preset.spec, null);
              const saved = scenarios.data?.find((s) => s.id === v);
              if (saved) st().load(saved.spec, saved.id);
              toast(`Loaded “${preset?.label ?? saved?.spec.name}”`);
            }}
          >
            <option value="" disabled>
              Load…
            </option>
            <optgroup label="Presets">
              {PRESETS.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.label}
                </option>
              ))}
            </optgroup>
            {Boolean(scenarios.data?.length) && (
              <optgroup label="Saved scenarios">
                {scenarios.data!.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.spec.name}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void saveScenario()}
            disabled={issues.length > 0 || save.isPending}
          >
            <Save />
            {scenarioId ? "Update" : "Save"}
          </Button>
          <Button
            size="sm"
            onClick={() => void run("single")}
            disabled={!ready || create.isPending}
          >
            <Play />
            Run live
          </Button>
          <div className="flex items-center overflow-hidden rounded-md border">
            <Button
              size="sm"
              variant="secondary"
              className="rounded-none"
              onClick={() => void run("montecarlo")}
              disabled={!ready || create.isPending}
            >
              <ChartSpline />
              Monte Carlo ×
            </Button>
            <input
              type="number"
              aria-label="Monte Carlo runs"
              min={2}
              max={1000}
              value={mcRuns}
              onChange={(e) => setMcRuns(Math.max(2, Math.min(1000, Number(e.target.value) || 2)))}
              className="tabular h-8 w-14 border-l bg-surface-2 px-1.5 text-center font-mono text-sm outline-none"
            />
          </div>
        </div>
      </div>

      {issues.length > 0 && (
        <div
          role="alert"
          className="flex gap-3 rounded-lg border border-status-critical/40 bg-status-critical/10 px-4 py-3 text-sm"
        >
          <CircleAlert className="mt-0.5 size-4 shrink-0 text-bear-text" aria-hidden />
          <div>
            <p className="font-medium text-bear-text">Fix these before running:</p>
            <ul className="mt-1 list-disc pl-5 text-foreground">
              {issues.map((i, k) => (
                <li key={k}>
                  <button
                    type="button"
                    className="underline-offset-2 hover:underline"
                    onClick={() => {
                      const m = /^event-(\d+)$/.exec(i.where);
                      if (m) st().select(Number(m[1]));
                    }}
                  >
                    {i.message}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_440px]">
        <div className="flex min-w-0 flex-col gap-5">
          <Panel title="Scenario" icon={ScrollText} index={0}>
            <div className="grid gap-3 sm:grid-cols-4">
              <label className="flex flex-col gap-1 text-xs text-muted-foreground sm:col-span-2">
                Name
                <input
                  className={input}
                  value={scenario.name ?? ""}
                  aria-invalid={fieldIssue("name") ? true : undefined}
                  onChange={(e) => st().setScenario({ name: e.target.value })}
                />
              </label>
              <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                Agents
                <input
                  type="number"
                  className={cn(input, "tabular font-mono")}
                  value={scenario.n_agents ?? 0}
                  aria-invalid={fieldIssue("n_agents") ? true : undefined}
                  step={1000}
                  onChange={(e) => st().setScenario({ n_agents: Number(e.target.value) })}
                />
              </label>
              <div className="grid grid-cols-2 gap-2">
                <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                  Days
                  <input
                    type="number"
                    className={cn(input, "tabular font-mono")}
                    value={scenario.days ?? 5}
                    aria-invalid={fieldIssue("days") ? true : undefined}
                    onChange={(e) => st().setScenario({ days: Number(e.target.value) })}
                  />
                </label>
                <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                  Seed
                  <input
                    type="number"
                    className={cn(input, "tabular font-mono")}
                    value={scenario.seed ?? 0}
                    onChange={(e) =>
                      st().setScenario({ seed: Math.max(0, Number(e.target.value) || 0) })
                    }
                  />
                </label>
              </div>
              <label className="flex flex-col gap-1 text-xs text-muted-foreground sm:col-span-4">
                Description
                <input
                  className={input}
                  value={scenario.description ?? ""}
                  onChange={(e) => st().setScenario({ description: e.target.value })}
                />
              </label>
            </div>
            {(fieldIssue("n_agents") || fieldIssue("days") || fieldIssue("name")) && (
              <p role="alert" className="mt-2 text-xs text-bear-text">
                {fieldIssue("name") ?? fieldIssue("n_agents") ?? fieldIssue("days")}
              </p>
            )}
          </Panel>

          <Panel
            title="Event timeline"
            subtitle="Drag to move · double-click to add · shaded = market open (09:30–16:00)"
            icon={Sparkles}
            index={1}
            actions={
              <>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    const id = nextEventId(events);
                    st().upsertEvent(newEvent(id, 44));
                    st().select(id);
                  }}
                >
                  <Plus />
                  Event
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setHawkes((h) => !h)}
                  aria-expanded={hawkes}
                >
                  <Shuffle />
                  Random shocks
                </Button>
                <Button variant="outline" size="sm" onClick={() => setImportOpen(true)}>
                  <ScrollText />
                  Import headlines
                </Button>
              </>
            }
          >
            <div className="flex flex-col gap-3">
              {hawkes && <HawkesForm onDone={() => setHawkes(false)} />}
              <Timeline />
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-1.5">
                  <span className="size-2.5 rounded-full bg-narrative" /> Rumour / leak (narrative)
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="size-2.5 rotate-45 rounded-[2px] bg-official" /> News and
                  official events
                </span>
                <span>Dashed arcs link follow-ups to their parent</span>
              </div>
              {events.length > 0 && (
                <ul className="grid gap-1 sm:grid-cols-2">
                  {events.map((e) => (
                    <li key={e.id}>
                      <button
                        type="button"
                        onClick={() => st().select(e.id)}
                        className="flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-xs outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/60"
                      >
                        <Tag>#{e.id}</Tag>
                        <span className="font-mono text-muted-foreground">
                          {simClock(e.tick).label}
                        </span>
                        <span className="truncate">{e.label || e.kind}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </Panel>

          <Panel title="Event" icon={SlidersHorizontal} index={2}>
            {schema.data ? (
              <EventEditor enums={schema.data.enums ?? FALLBACK_ENUMS} />
            ) : (
              <Skeleton className="h-40" />
            )}
          </Panel>
        </div>

        <Panel
          title="Parameters"
          subtitle="Placeholder values are guesses, not fitted to data"
          icon={SlidersHorizontal}
          index={3}
          className="xl:sticky xl:top-4 xl:max-h-[calc(100vh-7rem)]"
          bodyClassName="overflow-y-auto"
          actions={
            <>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowDiff((d) => !d)}
                aria-pressed={showDiff}
              >
                <FileDiff />
                Diff
              </Button>
              <Button
                variant="ghost"
                size="sm"
                disabled={!defaults.data}
                onClick={() =>
                  defaults.data &&
                  st().setParameters(defaults.data.parameters as unknown as Parameters)
                }
              >
                <RotateCcw />
                Reset all
              </Button>
            </>
          }
        >
          {!schema.data || !parameters ? (
            <div className="flex flex-col gap-2">
              {Array.from({ length: 6 }, (_, i) => (
                <Skeleton key={i} className="h-10" />
              ))}
            </div>
          ) : showDiff ? (
            <DiffView schema={schema.data} />
          ) : (
            <ParameterPanel schema={schema.data} />
          )}
        </Panel>
      </div>
      <ImportHeadlines open={importOpen} onOpenChange={setImportOpen} />
    </div>
  );
}
