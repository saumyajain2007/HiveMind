# marketsim: build plan and issues

This file turns `HANDOFF.md` and `docs/design_notes.txt` into a build plan for the full product: the simulation engine, an API around it, and a web front end. The repo currently has only the scaffold (`config.py`, design notes, handoff). Everything below is still to be built.

The 25 issues are listed in build order. Each one has a scope, a task list, acceptance criteria and its dependencies, so it can be copied into a GitHub issue as it stands.

---

## 1. What we are building

An agent-based market simulator for a single stock. Up to a million agents with correlated traits live on several social platforms. News events and rumours spread through those platforms, change what agents believe, and agents trade on those beliefs in a batch auction. The market price then feeds back into the news. Running the simulation many times gives a distribution of possible price paths. That distribution is calibrated against history and backtested against a random walk.

The product has three parts:

1. **Engine** (`marketsim/`): a pure Python library, vectorised with NumPy. It has no web code and makes no network calls. It is specified in `HANDOFF.md` §4.
2. **API** (`api/`): a FastAPI service that builds scenarios, runs simulations as background jobs, streams ticks live over WebSocket, and serves the stored results.
3. **Web app** (`web/`): a dark, trading-terminal-style dashboard. You design a scenario, watch a run play out live (price, rumours spreading through the network, narratives mutating), then study Monte Carlo fans, calibration and backtests.

## 2. Stack

| Layer | Choice | Why |
|---|---|---|
| Engine | Python ≥3.11, NumPy, SciPy | As decided in the handoff: vectorised arrays, no per-agent objects |
| Engine plots / reports | matplotlib | Static plots for `run_demo` and the README |
| Python tooling | `uv` (env + lockfile), `ruff` (lint + format), `mypy` (engine + api), `pytest`, `pytest-benchmark` | Fast and reproducible |
| API | FastAPI, Pydantic v2, uvicorn, `websockets` | Typed schemas generated from `config.py`, OpenAPI for free, native WebSocket support |
| Jobs | `concurrent.futures.ProcessPoolExecutor` inside the API process, with a small job registry | No Redis or Celery needed in v1. Monte Carlo already parallelises over processes |
| Storage | SQLite (run index, via SQLModel) + one folder per run (`runs/<id>/`: `config.json`, `metrics.npz`, `paths.npy`, `lineage.json`) | Zero setup. Arrays stay as arrays |
| Front end | React 18, TypeScript, Vite | Standard and fast |
| Styling | Tailwind CSS + shadcn/ui (Radix primitives), Framer Motion | Accessible components, design tokens and polished motion |
| Charts | TradingView `lightweight-charts` (price, candles, volume); Apache ECharts (fan chart, histograms, ACF, awareness curves, lineage tree) | Canvas rendering that stays smooth with tens of thousands of points |
| Network view | Sigma.js (WebGL) + graphology, with ForceAtlas2 in a Web Worker | Draws thousands of nodes at 60 fps |
| Data and state | TanStack Query (REST), Zustand (live-run store), a typed WebSocket client | Server cache and live state kept separate |
| API types | `openapi-typescript`, generated from FastAPI's OpenAPI spec | Front end and back end can't drift apart |
| Front-end testing | Vitest + Testing Library, Playwright (end to end), MSW (mock API) | The front end can be built before the API is finished |
| Delivery | Docker Compose (`api` + `web` behind Caddy), GitHub Actions CI | One command to run everything |

## 3. Architecture

```
            ┌──────────────────────── web (React) ────────────────────────┐
            │ Scenario Builder │ Live Cockpit │ Monte Carlo │ Network │    │
            │ Narratives │ Calibration & Backtest │ Runs library           │
            └──────────┬───────────────────────────────▲──────────────────┘
               REST (TanStack Query)          WebSocket frames (10–20 fps)
                       │                               │
            ┌──────────▼───────────── api (FastAPI) ───┴──────────────────┐
            │ /config /scenarios /runs /montecarlo /calibrations          │
            │ /backtests /events/parse /graph                             │
            │ Job registry → ProcessPoolExecutor → engine                 │
            │ SQLite run index + runs/<id>/ artifacts                     │
            └──────────┬──────────────────────────────────────────────────┘
                       │ Python import (no HTTP)
            ┌──────────▼──────────── engine (marketsim) ──────────────────┐
            │ population → graph → events → items → diffusion → beliefs   │
            │ → trading + firms → market (batch auction) → sim loop       │
            │ montecarlo · calibration · backtest · event_parser · viz    │
            └─────────────────────────────────────────────────────────────┘
```

**Engine–API contract.** `Simulation` takes an optional `on_tick(frame: TickFrame)` callback and an optional `should_stop()` check. A `TickFrame` is a small, JSON-ready dict: tick, price, V_true, volume, mean investor confidence, IV, ATM call, the awareness count for each active item, items created this tick, and an optional awareness bitmap for a sampled set of nodes. The engine never imports FastAPI. The API never reaches into engine internals.

**Determinism.** Every run is fully determined by `(config, scenario, seed)`. The API stores all three, so any run can be replayed exactly, and the UI's "Replay" button relies on this.

## 4. Repository layout (target)

```
marketsim/
  HANDOFF.md  DECISIONS.md  DATA_SOURCES.md  README.md  issues.md
  docs/design_notes.txt          (user's notes, never edited)
  pyproject.toml  uv.lock
  marketsim/                     engine package (layout from HANDOFF §3)
  api/
    marketsim_api/  main.py  schemas.py  jobs.py  storage.py  routes/
    tests/
  web/
    src/  app/  components/  features/{builder,cockpit,montecarlo,network,narratives,analysis,runs}/
    src/lib/{api,ws,theme}/  tests/  e2e/
  tests/                         engine tests, one file per module
  benchmarks/bench.py
  docker-compose.yml  Caddyfile  .github/workflows/ci.yml
```

## 5. Design direction for the web app

The look is a **night-mode trading terminal**: dense and precise, but calm.

- **Palette:** background `#0A0D13`; panels `#11151D` with 1px `#1E2430` borders and a faint inner glow; text `#E6E9EF`, muted text `#8A93A6`. Up / bullish is teal `#2DD4BF`, down / bearish is coral `#FB7185`, narratives and rumours are violet `#A78BFA`, official events are amber `#FBBF24`, and V_true (the hidden fundamental value) is a dashed ice-blue `#7DD3FC`. Each platform has a fixed colour that is used everywhere (Twitter sky, Reddit orange, Friendship green, Instagram pink, TikTok cyan, YouTube red). All colours are checked for contrast and colour-blindness, and every series also has a shape or dash.
- **Type:** Inter for UI text; JetBrains Mono with tabular numbers for every price, count and parameter.
- **Motion:** Framer Motion for panel entry and layout changes. Numbers count up when they change. A pulse runs along the price line when an event is injected. Rumours spreading through the network are drawn as nodes lighting up. Every animation respects `prefers-reduced-motion`.
- **Layout:** a left icon rail for navigation, a top bar with the ticker strip (price, Δ%, IV, ATM call, run status), and resizable panel grids built on `react-resizable-panels`. `⌘K` opens a command palette.
- **Empty and loading states:** skeleton shimmer while data loads. Empty states include a one-click "Run demo scenario" button.
- A light theme exists, but dark is the default and gets most of the polish.

## 6. Phases and milestones

| Phase | Issues | Output |
|---|---|---|
| P0: Foundations | #1 | Monorepo, tooling and CI all green on an empty skeleton |
| P1: Engine core (HANDOFF M1–M4) | #2–#10 | A deterministic single run at 10k agents with metrics |
| P2: Prediction (M4–M6) | #11–#15 | Monte Carlo, calibration + recovery test, backtest, event parser, benchmarks |
| P3: API | #16–#18 | Runs as jobs, live streaming, every result type served |
| P4: Web app | #19–#25 | Pretty, live dashboard; end-to-end tests; Docker deploy |

**Parallel work.** Once #16 has frozen the schemas, the front end (#19–#24) can be built against MSW mocks while P1 and P2 continue. The engine issues follow the dependency order of `HANDOFF.md`.

**Labels used below:** `area:engine`, `area:api`, `area:web`, `area:infra`, `type:feature`, `type:test`, `type:docs`, `priority:P0/P1/P2`. Sizes: S ≤ ½ day, M ≈ 1 day, L ≈ 2–3 days.

---

## Issues

### #1 Repo foundations: tooling, CI and project skeleton
`area:infra` `priority:P0` · Size M · Depends on: none

Set up the monorepo so that every later issue lands into a working pipeline.

**Tasks**
- [ ] `pyproject.toml` managed by `uv`: engine package `marketsim`, API package `marketsim_api`, dev extras (pytest, ruff, mypy, pytest-benchmark, psutil). `requires-python >=3.11`.
- [ ] `web/` created with Vite + React + TS + Tailwind + shadcn/ui; `pnpm` lockfile; ESLint and Prettier.
- [ ] Pre-commit hooks: ruff, ruff-format, mypy on changed files, prettier.
- [ ] GitHub Actions: `engine` job (ruff, mypy, pytest -q), `api` job, `web` job (lint, typecheck, vitest, build). Pip and pnpm caches.
- [ ] Create `DECISIONS.md` and `DATA_SOURCES.md` with headings. Keep `config.py` as it is, `PLACEHOLDER` markers included.
- [ ] Extend `.gitignore` (`outputs/`, `runs/`, `web/node_modules`, `web/dist`, `.venv`).

**Acceptance criteria**
- CI is green on the skeleton. `uv run pytest -q` and `pnpm -C web build` both succeed locally.
- No commits land on `main` directly; branch protection is described in the README.

---

### #2 Population: Gaussian-copula traits, categories, platforms, latent attributes
`area:engine` `type:feature` `priority:P0` · Size L · Depends on: #1 · HANDOFF M1

**Tasks**
- [ ] `Population` stores one array per field, length N. `add_agents(n)` appends and never removes.
- [ ] Copula over `age, wealth, impulsiveness, risk_tolerance, knowledge, belief_tolerance, media_attention, loss_aversion`, using the marginals from HANDOFF §4 M1. Build R from `PopulationConfig.correlations`, repair it to PSD by eigenvalue clipping, then rescale to unit diagonal.
- [ ] Category: investor logit on log-wealth, knowledge and risk, with the intercept solved by bisection to hit `investor_share`. Softmax among investors (day trader / swing / long-term).
- [ ] Platform usage per platform (logistic on age, interests, knowledge) and intensity Beta.
- [ ] Activity hours: a peak hour per agent and `online_prob(hour)`.
- [ ] Latent attributes: offline `community` (age-sorted, lognormal chunk sizes), `interests` (Dirichlet over `TOPICS`, mixed with a community preference), `influence` (Pareto α≈1.5).
- [ ] State arrays: confidence, narrative_bias, held_narrative, perceived_value, cash, shares, entry_price, strategy_weights. Long-term investors start with a position.
- [ ] Media outlet nodes: `media_per_100k`, influence ×50, `media_credibility`, `media_bias`.
- [ ] Record in `DECISIONS.md` that `belief_tolerance`, `media_attention` and `loss_aversion` are extra fields. Leave `[TBD]` unimplemented.

**Acceptance criteria**
- `tests/test_population.py`: sample correlations within ±0.07 of the repaired target at 10k; investor share within ±1 pt; `add_agents` keeps every array the same length.
- Building 10k agents takes < 1 s.

---

### #3 Social graph layers + `layer_stats()` + `add_nodes`
`area:engine` `type:feature` `priority:P0` · Size L · Depends on: #2 · HANDOFF M1

**Tasks**
- [ ] `Layer` base class with `push(sharer_ids) -> float32[N]` and `stats()`.
- [ ] Directed Chung–Lu for Twitter (homophily by main interest) and Instagram (homophily by community). Lognormal out-degree scaled by activity, targets weighted by influence, a cumsum + `searchsorted` sampler, dedup through int64 keys, and a **receiver CSR** so `push` only touches the sharers' rows (`np.repeat` + `np.bincount`).
- [ ] Friendship: undirected stub matching inside communities, symmetrised, then triadic closure.
- [ ] Reddit: subs with topics, memberships by interest then Zipf sub size, sparse `M @ intensity` push.
- [ ] TikTok: algorithmic exposure, no edges. YouTube: creator→subscriber CSR (the lag queue is handled in #6).
- [ ] `layer_stats()`: degree percentiles, mean degree, reciprocity, sampled clustering, cross-layer Jaccard overlap.
- [ ] `add_nodes(new_ids)`: preferential attachment inside the new node's group, then rebuild the CSR.
- [ ] `DATA_SOURCES.md`: SNAP, Pew / Ofcom, Arctic Shift entries for each target statistic.

**Acceptance criteria**
- No self-loops or duplicate edges. At 10k agents the Twitter in-degree has max / median > 20. `add_nodes` leaves a valid graph.
- `layer_stats()` prints sensible numbers at 10k, and they are pasted into `DECISIONS.md`.

---

### #4 Events: dataclass, queue, Hawkes generator, seeding, broadcast
`area:engine` `type:feature` `priority:P0` · Size M · Depends on: #2 · HANDOFF M1

**Tasks**
- [ ] `Event` with exactly the user's fields plus `id` and `topic="finance"`.
- [ ] `EventQueue` (heapq by tick) and `load_events(path)` for JSON.
- [ ] `hawkes_events(mu, alpha, beta, n_ticks, rng)`: discrete-time self-exciting arrivals with randomised attributes.
- [ ] `seed_agents(event, pop, rng)` for each of `official / outlet / influencer / insider / anonymous`.
- [ ] Broadcast exposure on the first tick (`salience · media_attention · broadcast_rate`).
- [ ] At injection, a real event moves `V_true *= exp(true_impact)`.

**Acceptance criteria**
- Tests cover every seeding type (the seed sets have the right size and kind) and the Hawkes rate rises after a burst.

---

### #5 Items store and narrative lineage
`area:engine` `type:feature` `priority:P0` · Size M · Depends on: #4 · HANDOFF M2

**Tasks**
- [ ] Fixed-capacity slots (`max_items`) with per-slot arrays (sentiment, credibility, salience, complexity, true_impact, topic, parent, is_narrative, origin, born, total_shares).
- [ ] `awareness: bool[max_items, N]`; current sharers stored as index arrays.
- [ ] Slot retirement (salience < `retire_salience` and no sharers). Awareness is flushed into history before a slot is reused.
- [ ] Lineage log of every item ever created (`id, parent, origin, sentiment, credibility, born, final_aware`). `family_of(root_id)` helper.

**Acceptance criteria**
- A slot can be reused 1,000+ times with no stale awareness; lineage stays complete. Tests cover both.

---

### #6 Diffusion across platforms
`area:engine` `type:feature` `priority:P0` · Size L · Depends on: #3, #5 · HANDOFF M2

**Tasks**
- [ ] Online mask from activity hours, plus `trading_online_boost` for investors during market hours.
- [ ] Per-item exposure = Σ over layers of `reach · push(sharers)`, plus broadcast on the first tick and TikTok algorithmic exposure.
- [ ] `p_see = 1 − exp(−exposure · salience)` for agents who are online and not yet aware.
- [ ] Attention cap: concatenate the candidates, `lexsort` by (agent, −score), keep the first `attention_slots` per agent.
- [ ] Share probability as in HANDOFF §4 M2, step 6, including "talking your book". Each agent shares an item at most once.
- [ ] Salience decay. YouTube lag queue (16–96 ticks).

**Acceptance criteria**
- A single rumour gives an S-shaped awareness curve.
- With the same seed, higher salience gives strictly wider reach.
- Per-tick cost scales with the number of sharers, not with N × items (benchmark note in the PR).

---

### #7 Beliefs and narratives: belief, adopt, mutate, invent
`area:engine` `type:feature` `priority:P0` · Size L · Depends on: #6 · HANDOFF M2

**Tasks**
- [ ] Bounded-confidence belief step with `cred_eff`, `eff_sentiment` and `α` exactly as specified. Updates applied simultaneously with `np.add.at`, then clipped.
- [ ] `perceived_value *= exp(α · true_impact)` on awareness of a real event.
- [ ] Adopt (held_narrative, pull of narrative_bias).
- [ ] Mutate: at most one child per parent per tick (sentiment ×1.4 then clipped, credibility ×0.7, salience ×1.2). Mutators share the child instead.
- [ ] Invent: checked hourly, triggered by |1-day return| > threshold, one per direction per day; inventors become seeds.
- [ ] Per-tick pull toward narrative_bias, plus decay.

**Acceptance criteria**
- Tests: an item outside an agent's tolerance doesn't move them; mutations and an invention appear in the lineage of a scripted run.

---

### #8 Market: state, batch auction with square-root market maker, Black–Scholes
`area:engine` `type:feature` `priority:P0` · Size L · Depends on: #1 · HANDOFF M3

**Tasks**
- [ ] `MarketState`: price, V_true, per-tick history, daily OHLC, EWMA realised vol, IV (constant or a series), momentum helper, `bs_call`, ATM call logged each tick.
- [ ] `batch_auction(...)`: D(p) from sorted cumulative sums + `searchsorted`; bisection on r for `D(P·eʳ) = sign(r)·ADV·(r/(Y·σ))²` within ±cap; fill crossing orders at one price; market-maker inventory takes the residual; noise on open ticks.
- [ ] ADV = `adv_turnover · total shares held`.

**Acceptance criteria**
- `tests/test_market.py`: D(p) is monotone; buys − sells = market-maker residual; no fill outside a limit; the cap is respected; `bs_call` matches a reference value to 1e-8.

---

### #9 Trading agents and firms
`area:engine` `type:feature` `priority:P0` · Size L · Depends on: #7, #8 · HANDOFF M3

**Tasks**
- [ ] Expected return = category-weighted fundamental + chartist + sentiment. Strategy switching by EMA fitness with a softmax.
- [ ] Target position from risk tolerance, wealth, E and risk (`risk_aversion · iv_daily² · horizon`), clipped to [0, wealth]. Threshold lower for impulsive agents.
- [ ] Panic rule driven by loss aversion. Limit prices from impulsiveness and |E|, capped at ±10%.
- [ ] `PropFirms` (momentum + order-imbalance tanh), `Funds` (V_true with a 1-day lag), and a `DiscretionaryPolicy` protocol with a docstring-only LLM hook.

**Acceptance criteria**
- Unit tests for target sizing, threshold and panic. A 5-day run at 10k gives a non-flat price and positive volume.

---

### #10 Simulation loop, metrics, determinism and the `on_tick` hook
`area:engine` `type:feature` `priority:P0` · Size M · Depends on: #9 · HANDOFF M4

**Tasks**
- [ ] `Simulation(config, scenario, seed)` with the tick order from HANDOFF §4 M4, including feedback (price_move events, momentum, hourly invention, talking your book, panic).
- [ ] Metrics: price, V_true, volume, mean investor confidence, per-item awareness, and per-family awareness split by platform and category.
- [ ] `on_tick(TickFrame)` callback and `should_stop()` for cancellation (the API depends on both). Optional `node_sample` for streaming awareness bitmaps.
- [ ] `Simulation.run(n_ticks) -> results dict`. Results can be saved to and loaded from a folder (`save(path)` / `load(path)`).

**Acceptance criteria**
- Same seed → byte-identical results (test). The `on_tick` frames add < 5% runtime. A 5-day run at 10k takes < 30 s.

---

### #11 Monte Carlo runner, demo scenario, static plots
`area:engine` `type:feature` `priority:P1` · Size M · Depends on: #10 · HANDOFF M4

**Tasks**
- [ ] `montecarlo.run(config, scenario, R, workers)`: build the population and graph once, vary the dynamics seed, return (R, T) paths, quantiles and per-run summaries. Progress callback.
- [ ] `viz.py`: fan chart with V_true, event-family awareness, awareness by category / platform, lineage tree, stylised facts (return histogram vs normal, ACF of r vs |r|).
- [ ] `run_demo.py` with the scripted scenario (anonymous rumour on day 1, denial on day 3, earnings miss −5%). Writes `outputs/*.png` and `summary.json`, including kurtosis and |r| ACF at lags 1–10.

**Acceptance criteria**
- `python -m marketsim.run_demo --agents 10000 --days 5 --runs 20` finishes in < 10 min and writes every plot and `summary.json`.

---

### #12 Calibration and parameter-recovery test
`area:engine` `type:feature` `priority:P1` · Size M · Depends on: #11 · HANDOFF M5

**Tasks**
- [ ] `calibrate(observed_log_prices, events, param_space, n_trials, runs_per_trial)`: random search over `impact_Y, base_share, mu0, sentiment_scale`, minimising RMSE between the median simulated and observed log prices. Progress callback and a per-trial log (the UI plots it).
- [ ] `recovery_test()`: synthetic "observed" data from known parameters, calibrate, report the error per parameter.

**Acceptance criteria**
- The recovery test runs end to end. Its result table is written into `DECISIONS.md` and the README, including any parameter that turns out not to be identifiable.

---

### #13 Backtest with CRPS against a random walk
`area:engine` `type:feature` `priority:P1` · Size M · Depends on: #11 · HANDOFF M5

**Tasks**
- [ ] Sample CRPS (energy form); lognormal random-walk benchmark with trailing realised vol.
- [ ] `backtest(price_series, events, origins, horizon)`: only events at or before each origin, MC forward, CRPS for both models, mean skill score.
- [ ] CSV loader (`date, close`) + events JSON. Document both in the README.

**Acceptance criteria**
- CRPS matches a closed-form Gaussian CRPS within tolerance (test). A lookahead test shows that events after the origin are never used.

---

### #14 Offline LLM event parser and event-study labelling
`area:engine` `type:feature` `priority:P1` · Size M · Depends on: #4 · HANDOFF M5

**Tasks**
- [ ] `EVENT_JSON_SCHEMA`, `PROMPT_TEMPLATE` with 3 few-shot examples, `validate_event()` (clamps ranges, rejects unknown kinds / seedings).
- [ ] `parse_headlines(headlines, llm: Callable[[str], str], cache_path)`: disk cache keyed by hash; temperature is the caller's job.
- [ ] `abnormal_return_impact()`: market-model CAR, with the **lookahead-leakage warning** in its docstring.

**Acceptance criteria**
- Tests use a fake `llm`: bad JSON is rejected, out-of-range values are clamped, a cache hit skips the callable. The engine makes no network calls.

---

### #15 Benchmarks, scaling to 1M agents, engine docs
`area:engine` `type:docs` `priority:P1` · Size M · Depends on: #11 · HANDOFF M6

**Tasks**
- [ ] `benchmarks/bench.py`: build time, seconds per tick and peak RSS at 10k / 100k / 1M (with reduced degrees at 1M if RAM needs it; record what was used).
- [ ] README (engine section): what it is, how to run it, what is a placeholder, the recovery-test result, the benchmark table, known limitations, and the v2 list.
- [ ] Profile the top 3 hot spots and fix any that are easy wins.

**Acceptance criteria**
- The benchmark table is in the README. 100k agents run at < 0.5 s per tick on the dev machine (or the shortfall is explained in `DECISIONS.md`).

---

### #16 API foundation: schemas, run registry, storage
`area:api` `type:feature` `priority:P0` · Size L · Depends on: #1 (schemas), #10 (wiring)

**Tasks**
- [ ] FastAPI app (`api/marketsim_api/main.py`) with CORS, structured logging, `/api/health`, versioned prefix `/api/v1`.
- [ ] Pydantic models **generated from the `config.py` dataclasses** (a single source of truth). Each field carries its default, range, description and `placeholder: true` metadata, so the UI can badge placeholder values.
- [ ] `ScenarioSpec` (list of events + agent count + days + seed) and `RunSpec` (mode `single | montecarlo`, runs, workers).
- [ ] Storage: SQLite run index (id, name, status, created, spec hash, summary) + `runs/<id>/` artifacts.
- [ ] Endpoints: `GET /config/defaults`, `GET /config/schema`, CRUD `/scenarios`, `POST /runs`, `GET /runs`, `GET /runs/{id}`, `DELETE /runs/{id}`.
- [ ] Export the OpenAPI spec and generate TS types into `web/src/lib/api/types.ts` (CI checks they are up to date).

**Acceptance criteria**
- `pytest api/tests` covers schema round-trips (defaults → engine `Config` → defaults with no changes) and run CRUD. The schemas are frozen so web work can start with MSW mocks.

---

### #17 Job execution and live WebSocket streaming
`area:api` `type:feature` `priority:P0` · Size L · Depends on: #16, #10, #11

**Tasks**
- [ ] Job registry over `ProcessPoolExecutor` (queued / running / done / failed / cancelled). Concurrency limit from env.
- [ ] Worker runs the `Simulation` with `on_tick` and pushes frames through a `multiprocessing` queue; the API fans them out to subscribers.
- [ ] `WS /api/v1/runs/{id}/stream`: hello message (spec, node sample), then `TickFrame`s throttled to ≤20 fps with server-side coalescing; event and narrative-birth messages are never dropped; ends with a `done` message carrying the summary.
- [ ] Monte Carlo jobs stream progress (`runs_done / R`) and partial quantiles every k runs.
- [ ] `POST /runs/{id}/cancel` → `should_stop()`. Clients that reconnect get the buffered tail and then the live feed.

**Acceptance criteria**
- An integration test starts a 1-day run at 2k agents, receives ≥1 frame per simulated hour, and gets `done`. Cancelling stops the run within 1 s. A slow client never blocks the worker.

---

### #18 Results, analysis and parser endpoints
`area:api` `type:feature` `priority:P1` · Size M · Depends on: #17, #12, #13, #14

**Tasks**
- [ ] `GET /runs/{id}/series` (price, V_true, volume, confidence, OHLC, IV, ATM call; optional downsampling), `/quantiles`, `/paths?sample=50`, `/awareness` (per family × platform × category), `/lineage`, `/stylized-facts`, `/graph?layer=twitter&sample=3000` (sampled subgraph + node attributes).
- [ ] `POST /calibrations` and `POST /backtests` as jobs with progress streaming. `GET` returns the trial log / CRPS per origin.
- [ ] `POST /events/parse`: calls `parse_headlines` with a **pluggable provider**. Default is `none` (returns the prompt for manual paste). An optional provider is enabled only by an env var; it is never on by default, in line with the handoff's no-network rule for the engine.
- [ ] `POST /data/upload` for a `date, close` CSV and an events JSON (validated, stored per dataset).
- [ ] Gzip / orjson responses; float32 arrays sent as packed base64 where large.

**Acceptance criteria**
- Every endpoint is covered by a test using a small stored fixture run. OpenAPI types regenerate cleanly.

---

### #19 Web foundation: design system, app shell, live data layer
`area:web` `type:feature` `priority:P0` · Size L · Depends on: #1, #16 (types)

**Tasks**
- [ ] Tailwind theme tokens from §5 (colours, radii, shadows, glow, platform and sentiment palettes), Inter + JetBrains Mono, dark default + light theme.
- [ ] App shell: left icon rail (Runs, Builder, Cockpit, Monte Carlo, Network, Narratives, Analysis), top **ticker strip** (price, Δ% coloured with an arrow, IV, ATM call, run status pill), `⌘K` command palette, toasts, resizable panel grid.
- [ ] Shared components: `Panel`, `Stat` (count-up number), `Sparkline`, `PlaceholderBadge`, `SentimentChip`, `PlatformIcon`, skeleton loaders, empty states.
- [ ] Data layer: TanStack Query client on generated types, a typed WebSocket client with reconnection and backoff, a Zustand `liveRunStore` (ring buffers for frames, so the UI never re-renders per frame), and MSW handlers that replay a recorded run.
- [ ] Storybook (or Ladle) page with every shared component in both themes.

**Acceptance criteria**
- Lighthouse accessibility ≥ 95; every component passes axe; `prefers-reduced-motion` turns off non-essential animation; the shell looks finished with mock data.

---

### #20 Scenario Builder: parameters and event timeline
`area:web` `type:feature` `priority:P0` · Size L · Depends on: #19

**Tasks**
- [ ] Parameter panel generated from `/config/schema`: grouped accordions (Population, Graph, Diffusion, Beliefs, Trading, Market), sliders + numeric inputs with ranges, amber `PLACEHOLDER` badges, "reset to default" per field, and a diff view against the defaults.
- [ ] Platform toggles shown as cards with icons (Twitter / Reddit / Friendship on by default; Instagram / TikTok / YouTube off).
- [ ] **Event timeline editor**: a horizontal day / hour timeline with shaded market-hours bands; drag events onto it; an event card editor for every `Event` field (sentiment slider coloured coral → teal, seeding dropdown with icons, parent picker that draws a link); a Hawkes "add random shocks" generator.
- [ ] "Import headlines" drawer: paste headlines → `/events/parse` → review and edit the parsed events → add them to the timeline.
- [ ] Presets: "Demo: rumour → denial → earnings miss", "Quiet market", "Meme squeeze". Save / load scenarios. Run buttons: **Run live** and **Monte Carlo ×R**.

**Acceptance criteria**
- The demo scenario can be built from scratch in under a minute. Invalid input is blocked with inline messages. Scenarios round-trip through the API without changes.

---

### #21 Live Cockpit: watch a run as it happens
`area:web` `type:feature` `priority:P0` · Size L · Depends on: #19, #17

**Tasks**
- [ ] Main chart (`lightweight-charts`): 15-min candles plus a line mode, a dashed ice-blue V_true overlay, volume histogram, market-closed bands, and **event markers** (amber = official, violet = rumour / narrative, grey = price headline) with hover cards. A pulse runs along the price line when an event is injected.
- [ ] Side panels: mean investor confidence gauge (diverging coral ↔ teal), IV and ATM call stats, market-maker inventory sparkline, order-imbalance meter.
- [ ] **News feed**: items appear as they are born (origin icon, sentiment chip, credibility bar, awareness count rising live, a "mutated from #x" link).
- [ ] Awareness mini-chart showing the top 5 active items.
- [ ] Playback: live / pause / scrub (from the buffered frames), a speed indicator, cancel run, and "Replay with same seed".
- [ ] Sim clock: day N · HH:MM, with market open / closed status.

**Acceptance criteria**
- Holds 60 fps during a 10k-agent live run (React Profiler shows no per-frame re-render of the shell). Scrubbing back and forth is instant. Works with MSW replay and with a real API.

---

### #22 Monte Carlo view: fan chart, distributions, stylised facts
`area:web` `type:feature` `priority:P1` · Size M · Depends on: #19, #18

**Tasks**
- [ ] Fan chart (ECharts): 5/25/50/75/95% bands as layered translucent teal fills, median line, V_true, 20 faint sample paths on hover, event markers. Fills progressively while an MC job streams partial quantiles.
- [ ] Terminal-price distribution: histogram + KDE, with the random-walk benchmark density overlaid.
- [ ] Stylised-facts tab: return histogram vs normal (kurtosis badge), ACF of r vs |r| with confidence bands, volatility-clustering strip.
- [ ] Summary cards: P(price < start at day 5), median drawdown, VaR 95%, mean CRPS if a backtest is linked.
- [ ] Export PNG / SVG and CSV of the quantiles.

**Acceptance criteria**
- A 20-run × 5-day fan renders in < 300 ms; bands animate in smoothly; numbers match `summary.json` from the engine.

---

### #23 Network view: rumours spreading through the platforms
`area:web` `type:feature` `priority:P1` · Size L · Depends on: #19, #18, #17

**Tasks**
- [ ] Sigma.js WebGL graph of a sampled subgraph (2–5k nodes) from `/graph`. Layer switcher (Twitter / Reddit / Friendship / all) using the platform colours. ForceAtlas2 layout in a Web Worker, with the positions cached per run.
- [ ] Node encoding: size = influence (log), ring colour = category, fill = confidence (coral ↔ teal). Media outlets drawn as diamonds.
- [ ] **Spread animation**: pick an item, and nodes light up violet / amber the tick they become aware, synced to the cockpit's playback clock; sharers flash and their edges glow briefly.
- [ ] Hover / inspect card for an agent: traits, category, platforms, confidence history sparkline, position, items seen.
- [ ] Layer stats drawer (degree percentiles, reciprocity, clustering, Jaccard overlap) shown as small charts.

**Acceptance criteria**
- 5k nodes / 50k edges pan and zoom at ≥ 50 fps on integrated graphics. The spread animation matches the awareness counts from the API for the sampled nodes.

---

### #24 Narratives view: lineage tree and awareness breakdowns
`area:web` `type:feature` `priority:P1` · Size M · Depends on: #19, #18

**Tasks**
- [ ] **Lineage tree**: x = born tick, y = sentiment, curved lines to parents, marker size = final awareness, marker shape = origin (event / mutation / invention / price_news). Hovering a node highlights its whole family; clicking opens an item card (credibility decay down the chain, sharers over time).
- [ ] Event-family awareness curves (S-curves) with family colours; toggle absolute / share of population.
- [ ] Breakdown heat-map: family × (category, platform users), with a stacked-bar alternative.
- [ ] A "story" strip that turns the lineage into readable text: "Rumour #3 (anonymous) → mutated twice → reached 41% → denial #7 reached 28%".

**Acceptance criteria**
- The demo scenario shows the rumour family, at least one mutation and the denial linked to its parent. The heat-map values match `/awareness`.

---

### #25 Analysis and runs library, end-to-end tests, Docker deployment
`area:web` `area:infra` `type:feature` `priority:P1` · Size L · Depends on: #20–#24, #18

**Tasks**
- [ ] **Calibration page**: upload a `date, close` CSV + events JSON, pick the parameters and their ranges, start the job, live trial scatter (each trial's parameters vs RMSE), best-fit overlay on the observed series, and the recovery-test report (true vs recovered, per parameter).
- [ ] **Backtest page**: origins on a timeline, CRPS per origin (model vs random walk), skill-score headline card coloured by sign.
- [ ] **Runs library**: a table with status, spec hash, created time and headline stats; compare two runs side by side (overlaid fans, parameter diff); delete; duplicate into the Builder.
- [ ] Playwright end-to-end tests: build the demo scenario → run live → see the event markers → run MC → see the fan → open the lineage. Visual-regression snapshots for the key screens.
- [ ] `docker-compose.yml` (api, web static build behind Caddy, a persistent `runs/` volume), `make dev` / `make up`, and README sections for the full stack with screenshots / GIF.

**Acceptance criteria**
- `docker compose up` gives the working app at `http://localhost:8080`. The end-to-end suite is green in CI. The README has the stack overview, screenshots, run instructions, the benchmark table and the recovery-test result.

---

## Dependency graph (short form)

```
#1 ─┬─ #2 ─┬─ #3 ─┐
    │      └─ #4 ─┴─ #5 ─ #6 ─ #7 ─┐
    ├─ #8 ─────────────────────────┴─ #9 ─ #10 ─ #11 ─┬─ #12
    │                                                 ├─ #13
    │      #4 ─ #14                                   └─ #15
    ├─ #16 ─ #17 ─ #18   (#17 needs #10/#11; #18 needs #12–#14)
    └─ #19 ─┬─ #20
            ├─ #21 (needs #17)
            ├─ #22 (needs #18)
            ├─ #23 (needs #17, #18)
            ├─ #24 (needs #18)
            └─ #25 (needs #20–#24)
```

## Open questions for the user

1. **Hosted LLM provider for headline parsing in the API (#18).** The handoff rules out network calls in the engine. The plan keeps the provider off by default and enables it only through an env var. Is that what you want?
2. **Deployment target (#25).** The plan stops at local Docker Compose. Should it also go to a host (Fly.io, Render, or a VPS)?
3. **Multi-user.** v1 assumes one local user with no authentication. Is that enough?
