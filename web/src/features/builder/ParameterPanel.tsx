import { ChevronRight, RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";

import { PlaceholderBadge, PlatformIcon } from "@/components/badges";
import { Button } from "@/components/ui/button";
import type { Schemas } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import { PLATFORMS } from "@/lib/vocab";
import type { PlatformName } from "@/lib/vocab";

import { get, same } from "./diff";
import { builderStore, useBuilder } from "./store";

type FieldMeta = Schemas["FieldMeta"];

const SECTION_TITLES: Record<string, string> = {
  population: "Population",
  graph: "Graph",
  diffusion: "Diffusion",
  belief: "Beliefs",
  trading: "Trading",
  market: "Market",
};

const ON_BY_DEFAULT = new Set(["twitter", "reddit", "friendship"]);

function fmt(v: number): string {
  if (!Number.isFinite(v)) return String(v);
  if (Math.abs(v) >= 1000) return v.toLocaleString("en-US", { maximumFractionDigits: 2 });
  return String(Number(v.toPrecision(4)));
}

function NumberField({
  meta,
  value,
  onChange,
  compactLabel,
}: {
  meta: FieldMeta;
  value: number;
  onChange: (v: number) => void;
  compactLabel?: string;
}) {
  const [text, setText] = useState<string | null>(null);
  const lo = meta.min ?? 0;
  const hi = meta.max ?? Math.max(1, value * 2);
  const isInt = meta.kind === "int";
  // sliders cover the plausible range around the default, the box accepts the full range
  const sliderHi = Math.min(
    hi,
    Math.max(Math.abs(Number(meta.default)) * 4, lo + (hi - lo) * 0.05, 1),
  );
  const step = isInt ? 1 : (sliderHi - lo) / 200;
  const err =
    text != null && (text.trim() === "" || !Number.isFinite(Number(text)))
      ? "Enter a number"
      : text != null && (Number(text) < lo || Number(text) > hi)
        ? `Allowed range ${fmt(lo)} to ${fmt(hi)}`
        : text != null && isInt && !Number.isInteger(Number(text))
          ? "Whole numbers only"
          : null;
  const id = `p-${meta.key}${compactLabel ? `-${compactLabel}` : ""}`;
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <div className="flex items-center gap-2">
        {compactLabel && (
          <label htmlFor={id} className="w-24 shrink-0 truncate text-xs text-muted-foreground">
            {compactLabel}
          </label>
        )}
        <input
          type="range"
          min={lo}
          max={Math.max(sliderHi, value)}
          step={step}
          value={value}
          aria-label={`${compactLabel ?? meta.name} slider`}
          onChange={(e) => {
            setText(null);
            onChange(isInt ? Math.round(Number(e.target.value)) : Number(e.target.value));
          }}
          className="h-1.5 min-w-0 flex-1 cursor-pointer accent-[var(--primary)]"
        />
        <input
          id={id}
          aria-label={compactLabel ? undefined : `${meta.name} value`}
          inputMode="decimal"
          value={text ?? fmt(value)}
          aria-invalid={err ? true : undefined}
          aria-describedby={err ? `${id}-err` : undefined}
          onChange={(e) => {
            setText(e.target.value);
            const v = Number(e.target.value);
            if (
              e.target.value.trim() !== "" &&
              Number.isFinite(v) &&
              v >= lo &&
              v <= hi &&
              (!isInt || Number.isInteger(v))
            )
              onChange(v);
          }}
          onBlur={() => !err && setText(null)}
          className={cn(
            "tabular h-7 w-24 rounded-md border bg-surface-2 px-2 text-right font-mono text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
            err && "border-destructive",
          )}
        />
      </div>
      {err && (
        <p id={`${id}-err`} role="alert" className="text-right text-[11px] text-bear-text">
          {err}
        </p>
      )}
    </div>
  );
}

function JsonField({
  meta,
  value,
  onChange,
}: {
  meta: FieldMeta;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const [text, setText] = useState(() => JSON.stringify(value, null, 1));
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className="flex flex-col gap-1">
      <textarea
        aria-label={`${meta.name} (JSON)`}
        value={text}
        spellCheck={false}
        rows={Math.min(8, text.split("\n").length)}
        onChange={(e) => {
          setText(e.target.value);
          try {
            const v = JSON.parse(e.target.value) as unknown;
            setErr(null);
            onChange(v);
          } catch {
            setErr("Not valid JSON yet");
          }
        }}
        className={cn(
          "w-full resize-y rounded-md border bg-surface-2 p-2 font-mono text-[11px] outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
          err && "border-destructive",
        )}
      />
      {err && (
        <p role="alert" className="text-[11px] text-bear-text">
          {err}
        </p>
      )}
    </div>
  );
}

function PlatformCards({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div
      className="grid grid-cols-2 gap-2 sm:grid-cols-3"
      role="group"
      aria-label="Platforms switched on"
    >
      {(Object.keys(PLATFORMS) as PlatformName[]).map((p) => {
        const on = value.includes(p);
        return (
          <button
            key={p}
            type="button"
            aria-pressed={on}
            onClick={() =>
              onChange(
                on
                  ? value.filter((x) => x !== p)
                  : [...value, p].sort((a, b) => order(a) - order(b)),
              )
            }
            className={cn(
              "flex flex-col items-start gap-1 rounded-lg border p-2.5 text-left transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
              on
                ? "border-primary/50 bg-primary/[0.07]"
                : "border-dashed bg-surface-2 hover:border-border-strong",
            )}
          >
            <PlatformIcon platform={p} />
            <span className="text-[11px] text-muted-foreground">
              {on ? "On" : "Off"}
              {ON_BY_DEFAULT.has(p) ? " · v1 default" : ""}
            </span>
          </button>
        );
      })}
    </div>
  );
}
const order = (p: string) => Object.keys(PLATFORMS).indexOf(p);

function FieldRow({ meta }: { meta: FieldMeta }) {
  const params = useBuilder((s) => s.parameters);
  const value = get(params, meta.key);
  const [section, field] = meta.key.split(".") as [string, string];
  const changed = !same(value, meta.default);
  const set = (v: unknown) => builderStore.getState().setParam(section, field, v);
  let control;
  if (meta.key === "graph.platforms") {
    control = <PlatformCards value={(value as string[]) ?? []} onChange={set} />;
  } else if (meta.kind === "int" || meta.kind === "float") {
    control = <NumberField meta={meta} value={Number(value)} onChange={set} />;
  } else if (meta.kind === "bool") {
    control = (
      <input
        type="checkbox"
        checked={Boolean(value)}
        onChange={(e) => set(e.target.checked)}
        aria-label={meta.name}
      />
    );
  } else if (meta.kind === "map" && value && typeof value === "object") {
    const m = value as Record<string, number>;
    control = (
      <div className="flex flex-col gap-1.5">
        {Object.entries(m).map(([k, v]) => (
          <NumberField
            key={k}
            meta={{ ...meta, default: (meta.default as Record<string, number>)[k] ?? v }}
            value={v}
            compactLabel={k.replace("_", " ")}
            onChange={(nv) => set({ ...m, [k]: nv })}
          />
        ))}
      </div>
    );
  } else {
    control = (
      <JsonField key={JSON.stringify(meta.default)} meta={meta} value={value} onChange={set} />
    );
  }
  return (
    <div
      className={cn("flex flex-col gap-2 rounded-lg px-2 py-2.5", changed && "bg-primary/[0.04]")}
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
            <span className="font-mono text-[13px]">{meta.name}</span>
            {meta.placeholder && <PlaceholderBadge />}
            {changed && <span className="text-[11px] font-normal text-primary">changed</span>}
          </p>
          <p className="text-xs text-muted-foreground">{meta.description}</p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="size-7 shrink-0"
          disabled={!changed}
          aria-label={`Reset ${meta.name} to default`}
          onClick={() => set(meta.default)}
        >
          <RotateCcw className="size-3.5" />
        </Button>
      </div>
      {control}
    </div>
  );
}

export function ParameterPanel({ schema }: { schema: Schemas["ConfigSchema"] }) {
  const params = useBuilder((s) => s.parameters);
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const sections = useMemo(
    () =>
      schema.sections.map((s) => ({
        ...s,
        fields: s.fields.filter(
          (f) => !q || f.key.toLowerCase().includes(q) || f.description.toLowerCase().includes(q),
        ),
        changed: s.fields.filter((f) => !same(get(params, f.key), f.default)).length,
      })),
    [schema, q, params],
  );
  return (
    <div className="flex flex-col gap-2">
      <input
        type="search"
        placeholder="Search parameters…"
        aria-label="Search parameters"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        className="h-8 rounded-md border bg-surface-2 px-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
      />
      {sections.map((s) =>
        s.fields.length === 0 ? null : (
          <details
            key={s.name}
            className="group rounded-lg border bg-surface-2/40"
            open={Boolean(q) || s.name === "graph"}
          >
            <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring/60 [&::-webkit-details-marker]:hidden">
              <ChevronRight
                className="size-4 transition-transform group-open:rotate-90"
                aria-hidden
              />
              {SECTION_TITLES[s.name] ?? s.name}
              <span className="ml-auto font-mono text-[11px] font-normal text-muted-foreground">
                {s.changed ? `${s.changed} changed · ` : ""}
                {s.fields.length}
              </span>
            </summary>
            <div className="flex flex-col divide-y px-1 pb-1">
              {s.fields.map((f) => (
                <FieldRow key={f.key} meta={f} />
              ))}
            </div>
          </details>
        ),
      )}
    </div>
  );
}
