import { useStore } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import { createStore } from "zustand/vanilla";

import type { Schemas } from "@/lib/api/client";

import { same } from "./diff";
import { DEMO } from "./presets";

type ScenarioSpec = Schemas["ScenarioSpec"];
type EventSpec = Schemas["EventSpec"];
export type Parameters = Schemas["Parameters"];

export interface BuilderState {
  scenario: ScenarioSpec;
  /** null = engine defaults (filled in from /config/defaults on first load). */
  parameters: Parameters | null;
  /** The engine defaults `parameters` started from; fields still equal to it follow new defaults. */
  base: Parameters | null;
  /** Parameters copied from a run: kept as they are when the engine defaults change. */
  pinned: boolean;
  scenarioId: string | null;
  selected: number | null;
  setScenario: (patch: Partial<ScenarioSpec>) => void;
  load: (spec: ScenarioSpec, id?: string | null, parameters?: Parameters | null) => void;
  setParameters: (p: Parameters) => void;
  /** Move to new engine defaults, keeping every field the user changed. */
  rebase: (defaults: Parameters) => void;
  setParam: (section: string, field: string, value: unknown) => void;
  upsertEvent: (e: EventSpec) => void;
  removeEvent: (id: number) => void;
  addEvents: (events: EventSpec[]) => void;
  select: (id: number | null) => void;
}

const sortEvents = (events: EventSpec[]) =>
  [...events].sort((a, b) => a.tick - b.tick || a.id - b.id);

export const builderStore = createStore<BuilderState>()(
  persist(
    (set) => ({
      scenario: DEMO,
      parameters: null,
      base: null,
      pinned: false,
      scenarioId: null,
      selected: null,
      setScenario: (patch) => set((s) => ({ scenario: { ...s.scenario, ...patch } })),
      load: (spec, id = null, parameters) =>
        set((s) => ({
          scenario: { ...spec, events: sortEvents(spec.events ?? []) },
          scenarioId: id,
          selected: null,
          ...(parameters === undefined
            ? {}
            : {
                parameters,
                pinned: parameters !== null,
                base: parameters === null ? null : s.base,
              }),
        })),
      setParameters: (parameters) => set({ parameters, base: parameters, pinned: false }),
      rebase: (defaults) =>
        set((s) => {
          type P = Record<string, Record<string, unknown>>;
          const cur = s.parameters as unknown as P | null;
          const old = s.base as unknown as P | null;
          const d = defaults as unknown as P;
          const out: P = {};
          for (const [sec, fields] of Object.entries(d)) {
            out[sec] = {};
            for (const [f, v] of Object.entries(fields)) {
              const mine = cur?.[sec]?.[f];
              // without a record of the old defaults we cannot tell edits from stale defaults
              const edited = old != null && mine !== undefined && !same(mine, old[sec]?.[f]);
              out[sec][f] = edited ? mine : v;
            }
          }
          return { parameters: out as unknown as Parameters, base: defaults, pinned: false };
        }),
      setParam: (section, field, value) =>
        set((s) => {
          if (!s.parameters) return {};
          const sec = (s.parameters as unknown as Record<string, Record<string, unknown>>)[section];
          return {
            parameters: {
              ...s.parameters,
              [section]: { ...sec, [field]: value },
            } as Parameters,
          };
        }),
      upsertEvent: (e) =>
        set((s) => {
          const events = s.scenario.events ?? [];
          const rest = events.filter((x) => x.id !== e.id);
          return { scenario: { ...s.scenario, events: sortEvents([...rest, e]) } };
        }),
      removeEvent: (id) =>
        set((s) => ({
          selected: s.selected === id ? null : s.selected,
          scenario: {
            ...s.scenario,
            // follow-ups of a removed event lose their parent
            events: (s.scenario.events ?? [])
              .filter((e) => e.id !== id)
              .map((e) => (e.parent === id ? { ...e, parent: -1 } : e)),
          },
        })),
      addEvents: (events) =>
        set((s) => ({
          scenario: {
            ...s.scenario,
            events: sortEvents([...(s.scenario.events ?? []), ...events]),
          },
        })),
      select: (selected) => set({ selected }),
    }),
    {
      name: "marketsim-builder",
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({
        scenario: s.scenario,
        parameters: s.parameters,
        base: s.base,
        pinned: s.pinned,
        scenarioId: s.scenarioId,
      }),
    },
  ),
);

export function useBuilder<T>(selector: (s: BuilderState) => T): T {
  return useStore(builderStore, selector);
}

export function nextEventId(events: EventSpec[] | undefined): number {
  return Math.max(-1, ...(events ?? []).map((e) => e.id)) + 1;
}

export interface Issue {
  where: string;
  message: string;
}

/** Client-side checks that mirror the API's ScenarioSpec validation. */
export function validateScenario(s: ScenarioSpec): Issue[] {
  const out: Issue[] = [];
  const nTicks = (s.days ?? 5) * 96;
  if (!s.name?.trim()) out.push({ where: "name", message: "Give the scenario a name." });
  if (!Number.isInteger(s.n_agents) || s.n_agents! < 100 || s.n_agents! > 2_000_000)
    out.push({
      where: "n_agents",
      message: "Agents must be a whole number from 100 to 2,000,000.",
    });
  if (!Number.isInteger(s.days) || s.days! < 1 || s.days! > 250)
    out.push({ where: "days", message: "Days must be a whole number from 1 to 250." });
  const events = s.events ?? [];
  const byId = new Map(events.map((e) => [e.id, e]));
  if (byId.size !== events.length)
    out.push({ where: "events", message: "Event ids must be unique." });
  for (const e of events) {
    const name = e.label || `event ${e.id}`;
    if (e.tick < 0 || e.tick >= nTicks)
      out.push({ where: `event-${e.id}`, message: `“${name}” is past the end of the run.` });
    if (e.parent >= 0) {
      const p = byId.get(e.parent);
      if (!p)
        out.push({
          where: `event-${e.id}`,
          message: `“${name}” follows up an event that no longer exists.`,
        });
      else if (p.tick > e.tick)
        out.push({
          where: `event-${e.id}`,
          message: `“${name}” comes before the event it follows up.`,
        });
    }
    for (const [k, lo, hi] of [
      ["sentiment", -1, 1],
      ["credibility", 0, 1],
      ["salience", 0, 1],
      ["complexity", 0, 1],
      ["true_impact", -0.5, 0.5],
    ] as const) {
      const v = e[k] ?? 0;
      if (!(v >= lo && v <= hi))
        out.push({
          where: `event-${e.id}`,
          message: `“${name}”: ${k.replace("_", " ")} must be in [${lo}, ${hi}].`,
        });
    }
  }
  return out;
}
