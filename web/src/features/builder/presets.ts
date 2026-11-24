import type { Schemas } from "@/lib/api/client";

type EventSpec = Schemas["EventSpec"];
type ScenarioSpec = Schemas["ScenarioSpec"];

const D = 96;
const OPEN = 38;

function ev(
  e: Partial<EventSpec> & Pick<EventSpec, "id" | "tick" | "kind" | "seeding">,
): EventSpec {
  return {
    ticker: 0,
    true_impact: 0,
    sentiment: 0,
    credibility: 0.5,
    salience: 0.5,
    complexity: 0.3,
    parent: -1,
    topic: "finance",
    label: null,
    ...e,
  };
}

/** Same events as `marketsim/scenarios.py` (HANDOFF §4 M4 demo). */
export const DEMO: ScenarioSpec = {
  name: "Demo: rumour → denial → earnings miss",
  description:
    "Anonymous acquisition rumour on day 1, the company's denial on day 3, then a real earnings miss (−5%) before the open on day 4.",
  n_agents: 10_000,
  days: 5,
  seed: 0,
  events: [
    ev({
      id: 0,
      tick: OPEN + 6,
      kind: "rumour",
      seeding: "anonymous",
      sentiment: 0.8,
      credibility: 0.2,
      salience: 0.8,
      complexity: 0.2,
      label: "Forum post: Acme in takeover talks",
    }),
    ev({
      id: 1,
      tick: 2 * D + OPEN + 2,
      kind: "statement",
      seeding: "official",
      sentiment: -0.6,
      credibility: 0.95,
      salience: 0.7,
      complexity: 0.1,
      parent: 0,
      label: "Acme: 'no talks with any party'",
    }),
    ev({
      id: 2,
      tick: 3 * D + OPEN - 8,
      kind: "earnings",
      seeding: "official",
      true_impact: -0.05,
      sentiment: -0.7,
      credibility: 0.95,
      salience: 0.8,
      complexity: 0.4,
      label: "Q3 earnings miss",
    }),
  ],
};

export const QUIET: ScenarioSpec = {
  name: "Quiet market",
  description: "No news at all: what the agents do on their own.",
  n_agents: 10_000,
  days: 5,
  seed: 0,
  events: [],
};

export const MEME: ScenarioSpec = {
  name: "Meme squeeze",
  description: "An influencer's moon call, then a forum follow-up the next morning.",
  n_agents: 10_000,
  days: 5,
  seed: 0,
  events: [
    ev({
      id: 0,
      tick: OPEN - 20,
      kind: "rumour",
      seeding: "influencer",
      sentiment: 1,
      credibility: 0.3,
      salience: 1,
      complexity: 0.1,
      label: "Influencer: 'shorts are trapped, to the moon'",
    }),
    ev({
      id: 1,
      tick: D + OPEN - 10,
      kind: "rumour",
      seeding: "anonymous",
      sentiment: 0.9,
      credibility: 0.25,
      salience: 0.9,
      complexity: 0.1,
      parent: 0,
      label: "Forum: 'squeeze not squoze'",
    }),
  ],
};

export const PRESETS = [
  { key: "demo", label: "Demo: rumour → denial → earnings miss", spec: DEMO },
  { key: "quiet", label: "Quiet market", spec: QUIET },
  { key: "meme", label: "Meme squeeze", spec: MEME },
] as const;

export function newEvent(id: number, tick: number): EventSpec {
  return ev({
    id,
    tick,
    kind: "rumour",
    seeding: "anonymous",
    sentiment: 0.5,
    credibility: 0.3,
    salience: 0.6,
    label: "New event",
  });
}
