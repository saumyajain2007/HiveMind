import { describe, expect, it } from "vitest";

import { branchingRatio, DEFAULT_HAWKES, hawkesEvents } from "./hawkes";
import { parseLine } from "./parseLine";
import { DEMO, newEvent } from "./presets";
import { builderStore, nextEventId, validateScenario } from "./store";
import type { Parameters } from "./store";

describe("validateScenario", () => {
  it("accepts the demo", () => {
    expect(validateScenario(DEMO)).toEqual([]);
  });
  it("flags events past the end, bad parents and out-of-range values", () => {
    const bad = {
      ...DEMO,
      days: 2,
      events: [
        { ...DEMO.events![0]!, sentiment: 2 },
        { ...DEMO.events![1]!, parent: 9 },
        { ...DEMO.events![2]! }, // day 4: past a 2-day run
      ],
    };
    const msgs = validateScenario(bad).map((i) => i.message);
    expect(msgs.some((m) => m.includes("sentiment"))).toBe(true);
    expect(msgs.some((m) => m.includes("no longer exists"))).toBe(true);
    expect(msgs.some((m) => m.includes("past the end"))).toBe(true);
  });
  it("needs a name and sane sizes", () => {
    const issues = validateScenario({ ...DEMO, name: " ", n_agents: 5, days: 0 });
    expect(issues.map((i) => i.where)).toEqual(
      expect.arrayContaining(["name", "n_agents", "days"]),
    );
  });
});

describe("builder store", () => {
  it("keeps events sorted and unlinks follow-ups of a removed event", () => {
    builderStore.getState().load(DEMO, null);
    builderStore.getState().upsertEvent({ ...newEvent(7, 0), label: "first" });
    expect(builderStore.getState().scenario.events![0]!.label).toBe("first");
    builderStore.getState().removeEvent(0);
    const denial = builderStore.getState().scenario.events!.find((e) => e.id === 1)!;
    expect(denial.parent).toBe(-1);
    expect(nextEventId(builderStore.getState().scenario.events)).toBe(8);
  });
});

describe("headline lines", () => {
  it("reads an optional day and time prefix", () => {
    expect(parseLine("2 10:30 | Acme misses")).toEqual({ text: "Acme misses", tick: 96 + 42 });
    expect(parseLine("Day 1 07:30 | x").tick).toBe(30);
    expect(parseLine("Plain headline")).toEqual({ text: "Plain headline", tick: 36 });
  });
});

describe("hawkes", () => {
  it("is deterministic, valid and self-exciting", () => {
    const a = hawkesEvents(DEFAULT_HAWKES, 960, 10);
    expect(a).toEqual(hawkesEvents(DEFAULT_HAWKES, 960, 10));
    expect(a[0]!.id).toBe(10);
    for (const e of a) {
      expect(e.sentiment).toBeGreaterThanOrEqual(-1);
      expect(e.sentiment).toBeLessThanOrEqual(1);
      if (e.kind === "rumour") expect(e.true_impact).toBe(0);
    }
    expect(branchingRatio({ ...DEFAULT_HAWKES, alpha: 0.4, beta: 0.5 })).toBeCloseTo(
      (0.4 * Math.exp(-0.5)) / (1 - Math.exp(-0.5)),
    );
  });
});

describe("stale saved parameters", () => {
  type P = Parameters;
  const oldDefaults = { market: { mm_news_pass_through: 1, impact_Y: 0.7 } } as unknown as P;
  const newDefaults = {
    market: { mm_news_pass_through: 0, impact_Y: 0.122, mm_inventory_skew: 0.3 },
  } as unknown as P;

  it("follows new engine defaults but keeps the user's own edits", () => {
    builderStore.getState().setParameters(oldDefaults);
    builderStore.getState().setParam("market", "impact_Y", 0.5); // the user's edit
    builderStore.getState().rebase(newDefaults);
    const m = (
      builderStore.getState().parameters as unknown as Record<string, Record<string, number>>
    ).market!;
    expect(m).toEqual({ mm_news_pass_through: 0, impact_Y: 0.5, mm_inventory_skew: 0.3 });
  });

  it("resets parameters saved before defaults were tracked", () => {
    builderStore.setState({ parameters: oldDefaults, base: null, pinned: false });
    builderStore.getState().rebase(newDefaults);
    expect(builderStore.getState().parameters).toEqual(newDefaults);
  });

  it("keeps a duplicated run's parameters as they are", () => {
    builderStore.getState().load(builderStore.getState().scenario, null, oldDefaults);
    expect(builderStore.getState().pinned).toBe(true);
    expect(builderStore.getState().parameters).toEqual(oldDefaults);
  });
});
