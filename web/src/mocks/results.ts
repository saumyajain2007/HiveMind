/**
 * Mock result, analysis, dataset and parser endpoints (#18). The JSON fixtures are real engine
 * output exported through the API (`uv run python -m marketsim_api.export_fixtures`), served for
 * any run id so every page shows genuine model results without a backend.
 */
import { http, HttpResponse } from "msw/http";

import type { Schemas } from "@/lib/api/client";

import awareness from "./fixtures/results/awareness.json";
import backtest from "./fixtures/results/backtest.json";
import calibration from "./fixtures/results/calibration.json";
import dataset from "./fixtures/results/dataset.json";
import graph from "./fixtures/results/graph.json";
import lineage from "./fixtures/results/lineage.json";
import nodeSeen from "./fixtures/results/node-seen.json";
import paths from "./fixtures/results/paths.json";
import quantiles from "./fixtures/results/quantiles.json";
import runMonteCarlo from "./fixtures/results/run-montecarlo.json";
import runSingle from "./fixtures/results/run-single.json";
import series from "./fixtures/results/series.json";
import seriesMc from "./fixtures/results/series-mc.json";
import stylized from "./fixtures/results/stylized.json";
import stylizedMc from "./fixtures/results/stylized-mc.json";

type RunDetail = Schemas["RunDetail"];

export const fixtures = {
  runSingle: runSingle as unknown as RunDetail,
  runMonteCarlo: runMonteCarlo as unknown as RunDetail,
  quantiles,
  calibration,
  backtest,
  dataset,
};

interface Ctx {
  getRun: (id: string) => RunDetail | undefined;
  addRun: (run: RunDetail) => void;
}

const notFound = (what: string) =>
  HttpResponse.json({ detail: `${what} not found` }, { status: 404 });

let scenarios = new Map<string, Schemas["ScenarioRecord"]>();
let datasets = new Map<string, Schemas["DatasetDetail"]>();
let counter = 0;

export function resetResultMocks(): void {
  scenarios = new Map();
  const ds = dataset as unknown as Schemas["DatasetDetail"];
  datasets = new Map([[ds.id, ds]]);
  counter = 0;
}
resetResultMocks();

function datasetRecord(d: Schemas["DatasetDetail"]): Schemas["DatasetRecord"] {
  const { id, name, created_at, n_days, first_date, last_date, n_events, sha256 } = d;
  return { id, name, created_at, n_days, first_date, last_date, n_events, sha256 };
}

function parseCsv(text: string): { dates: string[]; closes: number[] } {
  const [header, ...rows] = text.trim().split(/\r?\n/);
  const cols = (header ?? "")
    .toLowerCase()
    .split(",")
    .map((c) => c.trim());
  const di = cols.indexOf("date");
  const ci = cols.indexOf("close");
  if (di < 0 || ci < 0) throw new Error("expected a CSV with 'date' and 'close' columns");
  const dates: string[] = [];
  const closes: number[] = [];
  for (const row of rows) {
    const f = row.split(",");
    const c = Number(f[ci]);
    if (!Number.isFinite(c) || c <= 0) throw new Error(`bad close on ${f[di]}`);
    dates.push((f[di] ?? "").trim());
    closes.push(c);
  }
  if (closes.length < 2) throw new Error("need at least two days of prices");
  return { dates, closes };
}

function analysisRun(
  ctx: Ctx,
  mode: "calibration" | "backtest",
  body: { name?: string | null; dataset_id: string; n_agents?: number; seed?: number },
): RunDetail {
  const base = fixtures.runSingle;
  const id = `mock${mode.slice(0, 3)}${String(++counter).padStart(5, "0")}`;
  const now = new Date().toISOString();
  const ds = datasets.get(body.dataset_id);
  const fx = (mode === "calibration" ? calibration : backtest) as unknown as { run: RunDetail };
  const run: RunDetail = {
    ...base,
    ...fx.run,
    id,
    name: body.name ?? `${mode}: ${ds?.name ?? body.dataset_id}`,
    mode,
    status: "done",
    created_at: now,
    updated_at: now,
    n_agents: body.n_agents ?? 3000,
    spec: { ...base.spec, mode },
  };
  ctx.addRun(run);
  return run;
}

export function resultHandlers(ctx: Ctx) {
  const run = (id: unknown) => ctx.getRun(String(id));
  const isMc = (id: unknown) => run(id)?.mode === "montecarlo";
  return [
    http.get("*/api/v1/runs/:id/series", ({ params }) =>
      run(params.id) ? HttpResponse.json(isMc(params.id) ? seriesMc : series) : notFound("run"),
    ),
    http.get("*/api/v1/runs/:id/quantiles", ({ params }) =>
      !run(params.id)
        ? notFound("run")
        : isMc(params.id)
          ? HttpResponse.json(quantiles)
          : HttpResponse.json({ detail: "only Monte Carlo runs have quantiles" }, { status: 400 }),
    ),
    http.get("*/api/v1/runs/:id/paths", ({ params }) =>
      run(params.id) ? HttpResponse.json(paths) : notFound("run"),
    ),
    http.get("*/api/v1/runs/:id/awareness", ({ params }) =>
      run(params.id) ? HttpResponse.json(awareness) : notFound("run"),
    ),
    http.get("*/api/v1/runs/:id/lineage", ({ params }) =>
      run(params.id) ? HttpResponse.json(lineage) : notFound("run"),
    ),
    http.get("*/api/v1/runs/:id/stylized-facts", ({ params }) =>
      run(params.id) ? HttpResponse.json(isMc(params.id) ? stylizedMc : stylized) : notFound("run"),
    ),
    http.get("*/api/v1/runs/:id/graph", ({ params, request }) => {
      if (!run(params.id)) return notFound("run");
      const layer = new URL(request.url).searchParams.get("layer") ?? "all";
      const g = graph as unknown as { edges: [number, number, string][] };
      return HttpResponse.json(
        layer === "all" ? graph : { ...graph, edges: g.edges.filter((e) => e[2] === layer) },
      );
    }),
    http.get("*/api/v1/runs/:id/node-seen", ({ params }) =>
      run(params.id) ? HttpResponse.json(nodeSeen) : notFound("run"),
    ),
    http.post("*/api/v1/runs/:id/cancel", ({ params }) => {
      const r = run(params.id);
      if (!r) return notFound("run");
      if (r.status !== "running" && r.status !== "queued")
        return HttpResponse.json({ detail: `run is already ${r.status}` }, { status: 409 });
      const next = { ...r, status: "cancelled" as const, updated_at: new Date().toISOString() };
      ctx.addRun(next);
      return HttpResponse.json(next, { status: 202 });
    }),

    // scenarios
    http.get("*/api/v1/scenarios", () => HttpResponse.json([...scenarios.values()])),
    http.post("*/api/v1/scenarios", async ({ request }) => {
      const spec = (await request.json()) as Schemas["ScenarioSpec"];
      const now = new Date().toISOString();
      const rec = {
        id: `scn${String(++counter).padStart(6, "0")}`,
        created_at: now,
        updated_at: now,
        spec,
      };
      scenarios.set(rec.id, rec);
      return HttpResponse.json(rec, { status: 201 });
    }),
    http.put("*/api/v1/scenarios/:id", async ({ params, request }) => {
      const old = scenarios.get(String(params.id));
      if (!old) return notFound("scenario");
      const rec = {
        ...old,
        spec: (await request.json()) as Schemas["ScenarioSpec"],
        updated_at: new Date().toISOString(),
      };
      scenarios.set(rec.id, rec);
      return HttpResponse.json(rec);
    }),
    http.delete("*/api/v1/scenarios/:id", ({ params }) => {
      scenarios.delete(String(params.id));
      return new HttpResponse(null, { status: 204 });
    }),

    // headline parser: no provider in the mock, so it returns prompts, then validates pasted replies
    http.post("*/api/v1/events/parse", async ({ request }) => {
      const body = (await request.json()) as Schemas["ParseRequest"];
      const texts = body.headlines.map((h) => h.text);
      const prompts = texts.map(
        (t, i) =>
          `Convert the headline into one JSON event (see the schema).\nEarlier headlines: ${JSON.stringify(texts.slice(0, i))}\nHeadline: ${t}`,
      );
      if (!body.responses)
        return HttpResponse.json({ provider: "none", prompts, events: [], errors: [] });
      const events: Schemas["EventSpec"][] = [];
      const errors: string[] = [];
      body.responses.forEach((reply, i) => {
        try {
          const d = JSON.parse(
            reply.slice(reply.indexOf("{"), reply.lastIndexOf("}") + 1),
          ) as Record<string, number | string>;
          const clamp = (x: unknown, lo: number, hi: number) =>
            Math.max(lo, Math.min(hi, Number(x)));
          events.push({
            id: (body.first_id ?? 0) + i,
            tick: body.headlines[i]!.tick ?? 0,
            kind: String(d.kind ?? "rumour") as Schemas["EventSpec"]["kind"],
            ticker: 0,
            true_impact: clamp(d.true_impact ?? 0, -0.5, 0.5),
            sentiment: clamp(d.sentiment ?? 0, -1, 1),
            credibility: clamp(d.credibility ?? 0.5, 0, 1),
            salience: clamp(d.salience ?? 0.5, 0, 1),
            complexity: clamp(d.complexity ?? 0.3, 0, 1),
            seeding: String(d.seeding ?? "anonymous") as Schemas["EventSpec"]["seeding"],
            parent: -1,
            topic: "finance",
            label: texts[i]!.slice(0, 200),
          });
        } catch {
          errors.push(`headline ${i} could not be parsed: ${JSON.stringify(texts[i])}`);
        }
      });
      return HttpResponse.json({ provider: "manual", prompts, events, errors });
    }),

    // datasets
    http.get("*/api/v1/data", () => HttpResponse.json([...datasets.values()].map(datasetRecord))),
    http.get("*/api/v1/data/:id", ({ params }) => {
      const d = datasets.get(String(params.id));
      return d ? HttpResponse.json(d) : notFound("dataset");
    }),
    http.post("*/api/v1/data/upload", async ({ request }) => {
      const body = (await request.json()) as Schemas["DatasetUpload"];
      try {
        const { dates, closes } = parseCsv(body.csv);
        const id = `ds${String(++counter).padStart(8, "0")}`;
        const detail: Schemas["DatasetDetail"] = {
          id,
          name: body.name,
          created_at: new Date().toISOString(),
          n_days: closes.length,
          first_date: dates[0]!,
          last_date: dates[dates.length - 1]!,
          n_events: body.events?.length ?? 0,
          sha256: id.padEnd(64, "0"),
          dates,
          closes,
          events: body.events ?? [],
        };
        datasets.set(id, detail);
        return HttpResponse.json(datasetRecord(detail), { status: 201 });
      } catch (e) {
        return HttpResponse.json({ detail: (e as Error).message }, { status: 422 });
      }
    }),

    // analysis jobs finish at once in the mock and return the exported results
    http.post("*/api/v1/calibrations", async ({ request }) => {
      const body = (await request.json()) as Schemas["CalibrationCreate"];
      if (!datasets.has(body.dataset_id)) return notFound("dataset");
      return HttpResponse.json(analysisRun(ctx, "calibration", body), { status: 201 });
    }),
    http.post("*/api/v1/backtests", async ({ request }) => {
      const body = (await request.json()) as Schemas["BacktestCreate"];
      if (!datasets.has(body.dataset_id)) return notFound("dataset");
      return HttpResponse.json(analysisRun(ctx, "backtest", body), { status: 201 });
    }),
    http.get("*/api/v1/calibrations/:id", ({ params }) => {
      const r = run(params.id);
      return r?.mode === "calibration"
        ? HttpResponse.json({ ...calibration, run: r })
        : notFound("calibration");
    }),
    http.get("*/api/v1/backtests/:id", ({ params }) => {
      const r = run(params.id);
      return r?.mode === "backtest"
        ? HttpResponse.json({ ...backtest, run: r })
        : notFound("backtest");
    }),
  ];
}
