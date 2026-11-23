# Decisions

Every judgement call, simplification and `xfail` made while building marketsim, newest last.
Each entry: **date · issue · decision**, then a line of rationale.

## Process

- **2026-11-23 · #1 · Skeleton pushed straight to `main`.** The repo owner asked for issue #1 to be pushed directly to `main`, which overrides the handoff's "never commit to main" rule for this work. The README recommends turning on branch protection before engine work starts.
- **2026-11-23 · #1 · One Python project, two packages.** `marketsim` (engine) and `api/marketsim_api` are built from one `pyproject.toml` with hatchling. The API's dependencies live in the `api` extra, so the engine can still be installed without any web stack.
- **2026-11-23 · #1 · Python 3.12 pinned for development** (`.python-version`). `requires-python >=3.11` as in the handoff, and CI tests both 3.11 and 3.12 for the engine.
- **2026-11-23 · #1 · `config.py` excluded from `ruff format`.** It is the hand-written design-phase source of truth; linting still applies.
- **2026-11-23 · #1 · React 19 instead of the React 18 named in `issues.md`.** It is the current release and shadcn/ui targets it; nothing in the plan depends on 18.
- **2026-11-23 · #1 · TypeScript pinned to 6.0.x.** TypeScript 7 (the native port) is out, but `typescript-eslint` 8.x supports only `<6.1`. Move to 7 when typescript-eslint does.
- **2026-11-23 · #1 · `httpx2` instead of `httpx` for the API test client.** Current Starlette deprecates `httpx` in `TestClient`.
- **2026-11-23 · #1 · Pre-commit hooks are local (`language: system`).** They call `uv run` / `pnpm`, so hook versions always match the lockfiles. Ruff uses `force-exclude` so `config.py` stays unformatted even when pre-commit passes it by name.
- **2026-11-23 · #1 · pnpm through corepack.** Pinned with `packageManager` in `web/package.json`, so nobody needs a global pnpm install.

## Model

- **2026-11-23 · #3 · The graph reads the population through a `GraphPopulation` protocol** (`n`, `community`, `interests`, `influence`, `platform_use` (N×6 bool, `ALL_PLATFORMS` order), `platform_intensity` (N×6, 0 for non-users)). Issue #3 was built before #2, so tests use `marketsim.testing.StubPopulation`. The real `Population` (#2) must expose these fields under these names.
- **2026-11-23 · #3 · `push()` returns exposure already multiplied by the layer's `reach`.** The handoff writes both "Σ reach · push" (diffusion) and puts `reach` inside the Reddit and TikTok formulas; putting it inside every layer avoids applying it twice. Diffusion (#6) sums the layers directly. `trust` is stored on each layer for beliefs (#7).
- **2026-11-23 · #3 · One `push` signature for all layers:** `push(sharers, *, topic=0, popularity=None)`. Only TikTok uses `topic` and `popularity`; the default popularity is the number of sharers.
- **2026-11-23 · #3 · Follow direction.** Directed edges are follower → followee (subscriber → creator). "Out-degree" is the number of accounts followed (lognormal × activity); "in-degree" is the follower count (targets ∝ influence, which gives the heavy tail).
- **2026-11-23 · #3 · Friendship degree.** Each user initiates Binomial(d, ½) ties to partners weighted by their target degree d, so a user ends up with about d friends after symmetrising. Partners are drawn inside the offline community with probability `friendship_homophily`.
- **2026-11-23 · #3 · Number of subreddits = round(N / `reddit_agents_per_sub`)**, using all agents as the handoff says (not just Reddit users), with at least one sub per topic. The extra subs are split across topics in proportion to Reddit users' total interest. Popularity within a topic is Zipf (`reddit_zipf`).
- **2026-11-23 · #3 · YouTube homophily.** Subscriptions go to creators of the subscriber's main interest with probability `youtube_homophily` (new PLACEHOLDER), so a finance creator cluster can form like Twitter's.
- **2026-11-23 · #3 · New config fields** (all PLACEHOLDER): `degree_sigma = 0.8`, `reddit_zipf = 1.0`, `youtube_homophily = 0.5`.
- **2026-11-23 · #3 · `add_nodes` uses preferential attachment** with weight (followers + 1) for follows and subscriptions, (degree + 1) for friendship, and (sub size + 1) for Reddit, inside the group with the layer's homophily share. Influence is used only at build time. Newcomers start with no followers.
- **2026-11-23 · #3 · `layer_stats()` uses its own fixed RNG** for the clustering sample, so calling it never changes a simulation's random stream.

### `layer_stats()` at 10k agents (stub population, default config, seed 0)

```
[twitter] directed, 2514 users
  edges 85604  reciprocity 0.036  clustering 0.120
  in-degree   mean    34.1  p50     22  p90     59  p99    226  max   1044  (max/median 47.5)
  out-degree  mean    34.1  p50     24  p90     74  p99    163  max    269
[reddit] membership, 2087 users
  subs 25  memberships 5305
  subs/user   mean     2.5  p50      2  p90      4  p99      6  max      7
  sub size    mean   212.2  p50    189  p90    373  p99    434  max    444
[friendship] undirected, 9477 users
  edges 81599  clustering 0.270
  degree      mean    17.2  p50     14  p90     34  p99     65  max    153
[overlap] twitter~friendship 0.0016
```

Gaps against the configured means come from removing duplicate edges. Twitter follows land on popular accounts and friendships stay inside small communities, so duplicates are common: the realised Twitter out-degree is 34 (target 40) and friendship degree is 17 (target 20, plus 15% closure). Correcting for this is part of fitting to data (DATA_SOURCES.md), not done here. With all six layers, building takes 0.2 s at 10k and 3.6 s at 100k on the dev machine.

- **2026-11-23 · #8 · The market maker absorbs the imbalance left at the clearing price.** The clearing move solves `D(P·e^r) = sign(r)·ADV·(r/(Y·σ))²`. D is a step function, so at the solution the agents' net demand can differ slightly from the curve's value. All crossing orders fill in full and the market maker's inventory changes by exactly `sold − bought`.
- **2026-11-23 · #8 · Noise is applied before fills.** The unmodelled-flow noise `N(0, noise_frac·σ_daily/√26)` is added to the auction's log move, and the result is clipped to ±`circuit_breaker`. Orders are filled against this final price, so no order fills outside its limit, even with noise.
- **2026-11-23 · #8 · σ in the impact law is the EWMA realised daily vol.** It starts from `implied_vol/√252` and is updated at each close with λ = `vol_ewma_lambda`. Implied vol (constant or a per-tick series) feeds only the option signal and, later, agents' risk term.
- **2026-11-23 · #8 · Volume = max(bought, sold).** Every share bought by an agent was sold by an agent or by the market maker.
- **2026-11-23 · #8 · ATM call.** Logged every tick as `bs_call(P, P, option_maturity_days/365, risk_free_rate, IV)`, 30 days and r = 0 by default. New config fields (PLACEHOLDER): `option_maturity_days`, `risk_free_rate`, `vol_ewma_lambda`; plus `trading_days_per_year = 252`.
- **2026-11-23 · #8 · No market-maker depth.** ADV is floored at 1e-9 so the market maker's curve stays strictly increasing and the clearing move is unique. With no orders and no depth, the price does not move.

- **2026-11-23 · #14 · `Event` pulled forward from #4.** `marketsim/events.py` has only the `Event` record and the kind/seeding lists. The queue, Hawkes generator, seeding and broadcast are still issue #4.
- **2026-11-23 · #14 · New kind `statement`** for company statements such as confirmations and denials. The notes' kinds (earnings, macro, regulatory, product, rumour, leak) have no slot for the demo's "company denial". `price_move` is an internal kind (created by the simulation) and the parser rejects it.
- **2026-11-23 · #14 · The LLM gives `parent` as a batch index.** A model cannot know event ids, so the prompt lists the earlier headlines in the batch and the model names one by index; `parse_headlines` maps it to the event id. A parent that points forward or at itself is rejected. If a parent was skipped (`on_error="skip"`), the child gets `parent = -1`.
- **2026-11-23 · #14 · The LLM estimates `true_impact`** (clamped to ±0.5 log), told to use 0 for anything unverified. For calibration, replace it with the event-study label from `abnormal_return_impact`, which is never a forecast input (see its docstring).
- **2026-11-23 · #14 · `tick`, `ticker` and `id` never come from the LLM.** They come from the caller (headline timestamp, `ticker` argument, `first_id` counter).
- **2026-11-23 · #14 · The cache stores raw responses**, keyed by sha256 of the prompt version plus the full prompt (which includes the earlier headlines). Validation runs on every load, so tightening the validator needs no cache flush. The cache is written atomically and saved even when a batch fails part-way.
- **2026-11-23 · #14 · Event-study estimation window.** It ends before the event day, and before the event window if that starts earlier, so the event's own return never enters α and β. Abnormal returns are summed over the inclusive window `[event_idx + a, event_idx + b]` (default (0, 2)).

- **2026-11-23 · #16 · Parameter models are generated from `config.py` at import time.** Types and defaults come from the dataclasses. Descriptions and the `placeholder` flag come from the comments next to each field (read with `tokenize` + `ast`). Allowed ranges live in `config_schema.FIELD_RANGES`, and a test fails if a numeric field has no range or description. Fields with no comment in `config.py` get a description from `DESCRIPTION_OVERRIDES`, so `config.py` itself stays as written.
- **2026-11-23 · #16 · The `placeholder` flag follows the explicit PLACEHOLDER markers in `config.py`.** In practice nothing is fitted to data yet. Unmarked values (e.g. `twitter_mean_out`) are guesses too, but the UI badge shows only what the file marks.
- **2026-11-23 · #16 · JSON shapes for non-JSON config values.** Correlations `{(a, b): rho}` become `[{a, b, rho}]`. Per-category dicts keyed by integer constants are keyed by category name (`long_term`, `swing`, `day_trader`). Tuples become fixed-length arrays. The round trip defaults → engine `Config` → defaults is exact (tested).
- **2026-11-23 · #16 · Agent count and seed belong to the scenario,** not the parameters. A run's engine `Config` is the scenario's `n_agents` and `seed` plus the six parameter sections. `POST /runs` can override the seed.
- **2026-11-23 · #16 · Runs snapshot their scenario.** The full spec (engine version, mode, runs, seed, scenario, parameters) is copied into `runs/<id>/spec.json`, so editing a saved scenario never changes a past run. `spec_hash` covers only what affects results; names, descriptions, event labels and worker count are excluded.
- **2026-11-23 · #16 · Scenario events are validated and normalised.** Ids are auto-assigned when -1; parents must exist and come no later; ticks must fall inside the run; events are sorted by (tick, id). `price_move` is not allowed in a scenario because the engine creates it. Events get an optional `label` (headline text for the UI), which the engine ignores.
- **2026-11-23 · #16 · `sqlite3` from the standard library instead of SQLModel.** The index is two small tables, so an ORM adds a dependency for little gain. Each operation opens a short-lived connection (safe in FastAPI's thread pool), and the database runs in WAL mode.
- **2026-11-23 · #16 · `DELETE /runs/{id}` returns 409 for queued or running runs.** Cancelling comes with the job runner in #17.
- **2026-11-23 · #16 · The OpenAPI spec is committed** (`api/openapi.json`) and the web types are generated from it with `openapi-typescript`. CI fails if either is stale. Pydantic's mypy plugin is enabled.

- **2026-11-23 · #19 · Chart colours were validated, not eyeballed.** The dataviz palette checker (lightness band, chroma, colour-blind separation, contrast) was run against each theme's panel surface.
  - Platforms use the reference categorical hues in a passing order: Twitter blue, Reddit orange, Friendship aqua, Instagram yellow, TikTok violet, YouTube red. Worst adjacent CVD ΔE is 9.1 (light) / 8.4 (dark). The three default platforms also pass when every pair is compared.
  - The Tailwind 400 shades first proposed in `issues.md` failed the lightness band and were dropped.
  - Up/down marks are `#0d9488`/`#e11d48` (light) and `#10a5a0`/`#ea5f78` (dark).
- **2026-11-23 · #19 · Semantic and platform colours never share a chart.** Up≈Friendship, down≈YouTube, narrative≈TikTok and official≈Instagram are too close to tell apart. Network (#23) and Narratives (#24) must encode platform by layer switch or shape when they also show sentiment.
- **2026-11-23 · #19 · Separate text and mark tokens.** `--bull`/`--bear`/… are for marks; `--*-text` tokens are for text and meet 4.5:1. `--primary` is the UI accent (light `#0f766e`, 5.5:1 with white text), distinct from the up-mark colour. Contrast is enforced by axe in the e2e suite.
- **2026-11-23 · #19 · Live frames bypass React state.** Ring buffers (`SeriesBuffer`) take every frame; the store bumps `version` at most once per animation frame. Only the ticker and the open page re-render, never the shell.
- **2026-11-23 · #19 · The live-stream message format is defined by the web app** (`web/src/lib/live/types.ts`: hello / tick / event / narrative / done / error, `?after=<tick>` to resume). #17 must send exactly these.
- **2026-11-23 · #19 · Mock API by default in development.** MSW mocks every #16 route plus the #17 stream, which replays a synthetic recording of the demo scenario. These mock numbers are not engine output. The mock's config fixtures are exported from the real API (`export_openapi` writes them, and CI checks they are current).
- **2026-11-23 · #19 · An in-app `/design` gallery instead of Storybook or Ladle.** It shows every token and component in a dark and a light island side by side, needs no extra tooling (Storybook did not yet support Vite 8), and is covered by the axe e2e tests.
- **2026-11-23 · #19 · Playwright + axe instead of Lighthouse.** The e2e job runs axe (WCAG 2.1 AA including colour contrast) on all 8 pages in both themes. Lighthouse is not run in CI.
- **2026-11-23 · #19 · Pages other than Runs are lazy-loaded.** The main chunk is ~230 kB gzip (React, router, Radix, Motion, React Query), and the size-warning limit is raised to 800 kB.
- **2026-11-23 · #19 · Library versions are newer than the plan assumed:** React Router 8, MSW 3 (`onUnhandledFrame`), react-resizable-panels 4 (`Group`/`Panel`/`Separator`, numbers are pixels), Motion 14. `openapi-fetch` is given a per-call `fetch` so MSW's patch is seen in tests.

## Simplifications

_(none yet)_

## xfails

_(none yet)_

## Results

### Parameter-recovery test (#12)

_(pending)_

### Benchmarks (#15)

_(pending)_
