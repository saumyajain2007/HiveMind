/**
 * Mock API (MSW). Mirrors the real FastAPI routes (#16) and the live stream (#17), so the web
 * app can be built and tested without a running backend. Enabled in dev by VITE_API_MOCK=true.
 */
import { http, HttpResponse } from "msw/http";
import { ws } from "msw/ws";

import type { Schemas } from "@/lib/api/client";
import type { StreamMessage } from "@/lib/live/types";

import { configDefaults, configSchema } from "./fixtures";
import { makeRecording } from "./recording";

type RunDetail = Schemas["RunDetail"];
type ScenarioSpec = Schemas["ScenarioSpec"];

const VERSION = "0.1.0";

/** Messages per second sent by the mock stream (a 5-day run of 480 ticks takes ~25 s at 24). */
export const mockStream = { messagesPerSecond: 24 };

/** Deterministic fake sha256-looking hex string from a seed string. */
function hex(seed: string, n = 64): string {
  let h = 2166136261;
  let out = "";
  for (let i = 0; out.length < n; i++) {
    h = Math.imul(h ^ (seed.charCodeAt(i % seed.length) + i), 16777619) >>> 0;
    out += h.toString(16).padStart(8, "0");
  }
  return out.slice(0, n);
}

function runSpec(
  scenario: ScenarioSpec,
  mode: RunDetail["mode"],
  runs: number,
  seed: number,
): RunDetail["spec"] {
  return {
    engine_version: VERSION,
    mode,
    runs,
    workers: 1,
    seed,
    scenario,
    scenario_id: null,
    parameters: configDefaults.parameters,
  };
}

function sparkFromCloses(closes: number[]): number[] {
  return closes.map((c) => Math.round(c * 100) / 100);
}

/** In-memory run table, seeded with a few finished runs so the Runs page has content. */
export function seedRuns(now = Date.now()): Map<string, RunDetail> {
  const db = new Map<string, RunDetail>();
  const base = configDefaults.scenario;
  const seeds: Array<
    [string, string, number, number, RunDetail["mode"], number, RunDetail["status"]]
  > = [
    ["a1c4e9f02b7d", "Demo: rumour → denial → earnings miss", 7, 10_000, "montecarlo", 20, "done"],
    ["b83d0e5c91aa", "Quiet market (no events)", 11, 10_000, "single", 1, "done"],
    ["c2f7a6d4e810", "Meme squeeze, high impulsiveness", 3, 50_000, "single", 1, "done"],
    ["d9e1b3c57f26", "Earnings miss only", 5, 10_000, "single", 1, "failed"],
  ];
  seeds.forEach(([id, name, seed, n, mode, runs, status], i) => {
    const rec = makeRecording({ seed, nAgents: n });
    const created = new Date(now - (i + 1) * 3_600_000 * (i + 1.5)).toISOString();
    const scenario = { ...base, name, n_agents: n, seed };
    db.set(id, {
      id,
      name,
      status,
      mode,
      runs,
      n_agents: n,
      days: 5,
      seed,
      scenario_id: null,
      spec_hash: hex(`${id}:${seed}:${n}:${mode}`),
      created_at: created,
      updated_at: created,
      summary:
        status === "done"
          ? { ...rec.summary, price_spark: sparkFromCloses(rec.summary.daily_closes as number[]) }
          : null,
      error: status === "failed" ? "worker crashed: out of memory at tick 212 (mock)" : null,
      spec: runSpec(scenario, mode, runs, seed),
    });
  });
  return db;
}

let runs = seedRuns();
let counter = 0;

export function resetMockDb(): void {
  runs = seedRuns();
  counter = 0;
}

const health = () =>
  HttpResponse.json({ status: "ok", api_version: VERSION, engine_version: VERSION });

function toRecord(r: RunDetail): Schemas["RunRecord"] {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { spec, ...rest } = r;
  return rest;
}

export const handlers = [
  http.get("*/api/health", health),
  http.get("*/api/v1/health", health),
  http.get("*/api/v1/config/schema", () => HttpResponse.json(configSchema)),
  http.get("*/api/v1/config/defaults", () => HttpResponse.json(configDefaults)),

  http.get("*/api/v1/runs", ({ request }) => {
    const url = new URL(request.url);
    const status = url.searchParams.get("status");
    const limit = Number(url.searchParams.get("limit") ?? 50);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    const all = [...runs.values()]
      .filter((r) => !status || r.status === status)
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
    return HttpResponse.json({
      items: all.slice(offset, offset + limit).map(toRecord),
      total: all.length,
    });
  }),

  http.post("*/api/v1/runs", async ({ request }) => {
    const body = (await request.json()) as Schemas["RunCreate"];
    const scenario = body.scenario ?? configDefaults.scenario;
    const id = `mock${String(++counter).padStart(8, "0")}`;
    const now = new Date().toISOString();
    const seed = body.seed ?? scenario.seed ?? 0;
    const mode = body.mode ?? "single";
    const detail: RunDetail = {
      id,
      name: body.name ?? scenario.name ?? "Untitled",
      status: "running",
      mode,
      runs: body.runs ?? 1,
      n_agents: scenario.n_agents ?? 10_000,
      days: scenario.days ?? 5,
      seed,
      scenario_id: body.scenario_id ?? null,
      spec_hash: hex(
        `${seed}:${scenario.n_agents}:${mode}:${JSON.stringify(scenario.events ?? [])}`,
      ),
      created_at: now,
      updated_at: now,
      summary: null,
      error: null,
      spec: runSpec(scenario, mode, body.runs ?? 1, seed),
    };
    runs.set(id, detail);
    return HttpResponse.json(detail, { status: 201 });
  }),

  http.get("*/api/v1/runs/:id", ({ params }) => {
    const r = runs.get(String(params.id));
    return r
      ? HttpResponse.json(r)
      : HttpResponse.json({ detail: "run not found" }, { status: 404 });
  }),

  http.delete("*/api/v1/runs/:id", ({ params }) => {
    const r = runs.get(String(params.id));
    if (!r) return HttpResponse.json({ detail: "run not found" }, { status: 404 });
    if (r.status === "running" || r.status === "queued")
      return HttpResponse.json({ detail: "cancel it first" }, { status: 409 });
    runs.delete(r.id);
    return new HttpResponse(null, { status: 204 });
  }),

  http.get("*/api/v1/scenarios", () => HttpResponse.json([])),

  ws.link("ws://*/api/v1/runs/:id/stream").addEventListener("connection", ({ client, params }) => {
    const id = String(params.id);
    const run = runs.get(id);
    const rec = makeRecording({
      seed: run?.seed ?? 7,
      nAgents: run?.n_agents ?? 10_000,
      days: run?.days ?? 5,
    });
    const after = Number(new URL(client.url).searchParams.get("after") ?? -1);
    const queue: StreamMessage[] = [
      { ...rec.hello, run_id: id },
      ...rec.messages.filter((m) => !("tick" in m) || m.tick > after),
      { type: "done", summary: rec.summary },
    ];
    let i = 0;
    const timer = setInterval(() => {
      const m = queue[i++];
      if (!m) {
        clearInterval(timer);
        return;
      }
      client.send(JSON.stringify(m));
      if (m.type === "done" && run) {
        runs.set(id, {
          ...run,
          status: "done",
          updated_at: new Date().toISOString(),
          summary: {
            ...rec.summary,
            price_spark: sparkFromCloses(rec.summary.daily_closes as number[]),
          },
        });
      }
    }, 1000 / mockStream.messagesPerSecond);
    client.addEventListener("close", () => clearInterval(timer));
  }),
];
