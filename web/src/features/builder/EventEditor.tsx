import { EyeOff, Trash2 } from "lucide-react";
import type { ReactNode } from "react";

import { SentimentChip } from "@/components/badges";
import { Button } from "@/components/ui/button";
import type { Schemas } from "@/lib/api/client";
import { MINUTES_PER_TICK, simClock, TICKS_PER_DAY } from "@/lib/format";
import { cn } from "@/lib/utils";

import { builderStore, useBuilder } from "./store";
import { eventColor, SEEDING_ICON } from "./vocab";

type EventSpec = Schemas["EventSpec"];

const SEEDING_HELP: Record<string, string> = {
  official: "Company release: every outlet plus the most knowledgeable investors",
  outlet: "3–10 news outlets report it",
  influencer: "One account from the top 0.1% by influence",
  insider: "About 5 well-connected investors",
  anonymous: "One low-influence account",
};

function Field({
  label,
  htmlFor,
  children,
  hint,
}: {
  label: string;
  htmlFor?: string;
  children: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={htmlFor} className="text-xs font-medium text-muted-foreground">
        {label}
      </label>
      {children}
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

const input =
  "h-8 rounded-md border bg-surface-2 px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/60";

function Slider({
  id,
  value,
  min,
  max,
  step = 0.01,
  onChange,
  track,
}: {
  id: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (v: number) => void;
  track?: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-2 flex-1 cursor-pointer appearance-auto rounded-full accent-[var(--primary)]"
        style={track ? { background: track } : undefined}
      />
      <span className="tabular w-12 text-right font-mono text-xs">{value.toFixed(2)}</span>
    </div>
  );
}

export function EventEditor({ enums }: { enums: Schemas["Enumerations"] }) {
  const scenario = useBuilder((s) => s.scenario);
  const selected = useBuilder((s) => s.selected);
  const e = scenario.events?.find((x) => x.id === selected);
  if (!e) {
    return (
      <p className="text-sm text-muted-foreground">
        Select an event on the timeline to edit it, or double-click the timeline to add one.
      </p>
    );
  }
  const set = (patch: Partial<EventSpec>) =>
    builderStore.getState().upsertEvent({ ...e, ...patch });
  const clock = simClock(e.tick);
  const days = scenario.days ?? 5;
  const earlier = (scenario.events ?? []).filter((x) => x.id !== e.id && x.tick <= e.tick);
  const SeedIcon = SEEDING_ICON[e.seeding] ?? EyeOff;
  const id = (k: string) => `ev-${e.id}-${k}`;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <span className="size-3 rounded-sm" style={{ background: eventColor(e) }} aria-hidden />
        <span className="font-mono text-xs text-muted-foreground">
          #{e.id} · {clock.label}
        </span>
        <SentimentChip value={e.sentiment} className="ml-auto" />
      </div>
      <Field label="Headline (shown in the UI only)" htmlFor={id("label")}>
        <input
          id={id("label")}
          className={input}
          value={e.label ?? ""}
          onChange={(ev) => set({ label: ev.target.value })}
        />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Kind" htmlFor={id("kind")}>
          <select
            id={id("kind")}
            className={input}
            value={e.kind}
            onChange={(ev) => set({ kind: ev.target.value as EventSpec["kind"] })}
          >
            {enums.kinds.map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
        </Field>
        <Field
          label="Seeding (who hears it first)"
          htmlFor={id("seeding")}
          hint={SEEDING_HELP[e.seeding]}
        >
          <div className="relative">
            <SeedIcon
              className="pointer-events-none absolute top-2 left-2 size-4 text-muted-foreground"
              aria-hidden
            />
            <select
              id={id("seeding")}
              className={cn(input, "w-full pl-8")}
              value={e.seeding}
              onChange={(ev) => set({ seeding: ev.target.value as EventSpec["seeding"] })}
            >
              {enums.seedings.map((k) => (
                <option key={k}>{k}</option>
              ))}
            </select>
          </div>
        </Field>
        <Field label="Day" htmlFor={id("day")}>
          <select
            id={id("day")}
            className={input}
            value={clock.day}
            onChange={(ev) =>
              set({
                tick: (Number(ev.target.value) - 1) * TICKS_PER_DAY + (e.tick % TICKS_PER_DAY),
              })
            }
          >
            {Array.from({ length: days }, (_, d) => (
              <option key={d} value={d + 1}>
                Day {d + 1}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label="Time"
          htmlFor={id("time")}
          hint={clock.open ? "Market open" : "Market closed"}
        >
          <input
            id={id("time")}
            type="time"
            step={MINUTES_PER_TICK * 60}
            className={input}
            value={`${String(clock.hh).padStart(2, "0")}:${String(clock.mm).padStart(2, "0")}`}
            onChange={(ev) => {
              const [h, m] = ev.target.value.split(":").map(Number);
              if (h == null || m == null || Number.isNaN(h) || Number.isNaN(m)) return;
              set({
                tick: (clock.day - 1) * TICKS_PER_DAY + Math.floor((h * 60 + m) / MINUTES_PER_TICK),
              });
            }}
          />
        </Field>
      </div>
      <Field label="Sentiment: how it is presented (bearish ← → bullish)" htmlFor={id("sent")}>
        <Slider
          id={id("sent")}
          value={e.sentiment}
          min={-1}
          max={1}
          onChange={(v) => set({ sentiment: v })}
          track="linear-gradient(90deg, var(--bear), var(--muted) 50%, var(--bull))"
        />
      </Field>
      <div className="grid grid-cols-3 gap-3">
        <Field label="Credibility" htmlFor={id("cred")}>
          <Slider
            id={id("cred")}
            value={e.credibility}
            min={0}
            max={1}
            onChange={(v) => set({ credibility: v })}
          />
        </Field>
        <Field label="Salience" htmlFor={id("sal")}>
          <Slider
            id={id("sal")}
            value={e.salience}
            min={0}
            max={1}
            onChange={(v) => set({ salience: v })}
          />
        </Field>
        <Field label="Complexity" htmlFor={id("cx")}>
          <Slider
            id={id("cx")}
            value={e.complexity}
            min={0}
            max={1}
            onChange={(v) => set({ complexity: v })}
          />
        </Field>
      </div>
      <Field
        label="Follows up (parent)"
        htmlFor={id("parent")}
        hint="Denials, confirmations and corrections link to the original"
      >
        <select
          id={id("parent")}
          className={input}
          value={e.parent}
          onChange={(ev) => set({ parent: Number(ev.target.value) })}
        >
          <option value={-1}>None</option>
          {earlier.map((p) => (
            <option key={p.id} value={p.id}>
              #{p.id} {p.label || p.kind}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Topic" htmlFor={id("topic")}>
        <select
          id={id("topic")}
          className={input}
          value={e.topic ?? "finance"}
          onChange={(ev) => set({ topic: ev.target.value as EventSpec["topic"] })}
        >
          {enums.topics.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
      </Field>
      <Button
        variant="outline"
        size="sm"
        className="self-start text-bear-text"
        onClick={() => builderStore.getState().removeEvent(e.id)}
      >
        <Trash2 />
        Remove event
      </Button>
    </div>
  );
}
