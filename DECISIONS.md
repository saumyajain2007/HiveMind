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

- **2026-11-23 · #3 · The graph reads the population through a `GraphPopulation` protocol** (`n`, `community`, `interests`, `influence`, `platform_use` (N×6 bool, `ALL_PLATFORMS` order), `platform_intensity` (N×6, 0 for non-users)). `marketsim.population.Population` (#2) satisfies it; a test checks this with mypy and at runtime. #3 was first built on a stand-in population and redone on the real one after #2 was merged; the stand-in (`marketsim/testing.py`) is deleted.
- **2026-11-23 · #3 · A negative community or group means "no group".** Media outlets have `community = -1`. `sample_targets` used to index that as the last community, so half of the outlets' ties landed in one 18-person group. Stubs with a negative group now always draw from the whole pool (test: `test_negative_group_draws_from_whole_pool`).
- **2026-11-23 · #3 · `push()` returns exposure already multiplied by the layer's `reach`.** The handoff writes both "Σ reach · push" (diffusion) and puts `reach` inside the Reddit and TikTok formulas; putting it inside every layer avoids applying it twice. Diffusion (#6) sums the layers directly. `trust` is stored on each layer for beliefs (#7).
- **2026-11-23 · #3 · One `push` signature for all layers:** `push(sharers, *, topic=0, popularity=None)`. Only TikTok uses `topic` and `popularity`; the default popularity is the number of sharers.
- **2026-11-23 · #3 · Follow direction.** Directed edges are follower → followee (subscriber → creator). "Out-degree" is the number of accounts followed (lognormal × activity); "in-degree" is the follower count (targets ∝ influence, which gives the heavy tail).
- **2026-11-23 · #3 · Friendship degree.** Each user initiates Binomial(d, ½) ties to partners weighted by their target degree d, so a user ends up with about d friends after symmetrising. Partners are drawn inside the offline community with probability `friendship_homophily`.
- **2026-11-23 · #3 · Number of subreddits = round(N / `reddit_agents_per_sub`)**, using all agents as the handoff says (not just Reddit users), with at least one sub per topic. The extra subs are split across topics in proportion to Reddit users' total interest. Popularity within a topic is Zipf (`reddit_zipf`).
- **2026-11-23 · #3 · YouTube homophily.** Subscriptions go to creators of the subscriber's main interest with probability `youtube_homophily` (new PLACEHOLDER), so a finance creator cluster can form like Twitter's.
- **2026-11-23 · #3 · New config fields** (all PLACEHOLDER): `degree_sigma = 0.8`, `reddit_zipf = 1.0`, `youtube_homophily = 0.5`.
- **2026-11-23 · #3 · `add_nodes` uses preferential attachment** with weight (followers + 1) for follows and subscriptions, (degree + 1) for friendship, and (sub size + 1) for Reddit, inside the group with the layer's homophily share. Influence is used only at build time. Newcomers start with no followers.
- **2026-11-23 · #3 · `layer_stats()` uses its own fixed RNG** for the clustering sample, so calling it never changes a simulation's random stream.

### `layer_stats()` at 10k agents (real population from #2, default config, seed 0)

```
[twitter] directed, 2516 users
  edges 81799  reciprocity 0.031  clustering 0.140
  in-degree   mean    32.5  p50     20  p90     55  p99    213  max   1738  (max/median 86.9)
  out-degree  mean    32.5  p50     22  p90     72  p99    152  max    319
[reddit] membership, 2209 users
  subs 25  memberships 5893
  subs/user   mean     2.7  p50      3  p90      4  p99      6  max      8
  sub size    mean   235.7  p50    188  p90    411  p99    615  max    664
[friendship] undirected, 8961 users
  edges 77363  clustering 0.259
  degree      mean    17.3  p50     14  p90     34  p99     66  max    151
[overlap] twitter~friendship 0.0010
```

The 10,000 people come with 5 media outlets (`media_per_100k = 50`). The outlets are the five most-followed Twitter accounts (influence ×50), which is why Twitter's max/median is higher than on the stand-in (87 vs 48). Gaps against the configured means come from removing duplicate edges: follows land on popular accounts and friendships stay inside small communities, so the realised Twitter out-degree is 33 (target 40) and friendship degree is 17 (target 20, plus 15% closure). Correcting for this is part of fitting to data (DATA_SOURCES.md). With all six layers, building takes 0.1 s at 10k and 4.0 s at 100k on the dev machine.

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

- **2026-11-23 · #2 · Population by Kaisha Kapoor, merged from `issue-2-population`.** Gaussian copula over the eight traits (correlations repaired to PSD by eigenvalue clipping), investor logit with its intercept solved by bisection, softmax categories among investors, platform-use logits with intercepts solved to hit each platform's target share, Dirichlet interests mixed with a community preference, Pareto influence, media outlets. `belief_tolerance`, `media_attention` and `loss_aversion` are extra traits the model needs (not in the design notes); the notes' `[TBD]` field is not implemented. All new distribution parameters live in `PopulationConfig` and are marked PLACEHOLDER.
- **2026-11-23 · #2 · Fixes made when merging.** (1) Media outlets use every platform **except Friendship**, since an outlet has no offline friends (they previously got friendships, see the #3 entry on negative groups). (2) The struct-of-arrays fields are declared on `Population` so mypy and `GraphPopulation` see them. (3) ruff, ruff-format and mypy clean-ups. The branch had never gone through CI because CI runs only on `main` and on pull requests.
- **2026-11-23 · #16 · Nested config shapes travel as JSON.** #2 added settings such as `marginals` (`("beta", a, b, loc, scale)` per trait), `category_logits` (`(intercept, {trait: coef})` per category), `platform_params` (nested dicts) and `peak_hour_mix` (tuple of tuples). The API schema generator now converts any nesting recursively, using the engine default as a template so tuples and category-id keys come back exactly. Fixed-length number tuples become typed tuples with range checks. Other nested shapes are `kind: "json"` with their top-level keys checked; the engine validates the rest when it builds the population. A test edits nested fields through the API format and builds a population from the result.

- **2026-11-24 · #4 · `load_events` is strict.** Out-of-range values, unknown kinds or fields, and bad parents raise `ValueError`; nothing is clamped. Files are written by people, so a typo should fail loudly. (The LLM parser, #14, clamps instead.) `price_move` is only allowed for events the simulation creates (`allow_internal=True`).
- **2026-11-24 · #4 · Seeding details.**
  - *official*: all media outlets plus the top 0.5% of investors by knowledge.
  - *outlet*: 3–10 outlets, or all of them if fewer exist; 10k agents give only 5.
  - *influencer*: a person, not an outlet, from the top 0.1% by influence. Outlets have 50× influence and would otherwise fill that top slice.
  - *insider*: 5 investors from the best-connected 10%. "Well-connected" uses an optional `connectedness` array (e.g. total graph degree) and falls back to influence.
  - *anonymous*: one person with below-median influence.
- **2026-11-24 · #4 · Hawkes branching ratio.** An arrival excites later ticks by α·e^{-βk} for k ≥ 1, so the branching ratio is α·e^{-β}/(1 − e^{-β}) and the mean rate is μ/(1 − ratio). Synthetic attributes follow the kind: rumours are anonymous or influencer-seeded with no true impact; real kinds get true_impact ~ N(0, 0.02) with sentiment leaning the same way.
- **2026-11-24 · #5 · Shares stay in feeds for `share_ttl` ticks** (new PLACEHOLDER, 32 = 8 hours). The handoff's "current sharers" is read as *shares still visible in feeds*. With one-tick shares, followers who were offline in that single 15-minute tick never saw a post, and no rumour could spread. Each share is a (start tick, agents) batch; a share decided at tick t starts at t + 1, and seeds start at the item's birth. An item retires when it has faded and every share has left the feeds.
- **2026-11-24 · #5 · Full store evicts the faintest item.** Its record stays in the lineage with its retirement tick. The count is kept in `ItemStore.evicted`.
- **2026-11-24 · #5 · Family awareness is kept as one boolean row per family** (root item + descendants), updated on every `mark_aware`. #10 can report family reach after the individual items have retired. Follow-up events (a denial with `parent` = the rumour's event id) hang under the parent event's item.
- **2026-11-24 · #6 · Broadcast only for media-carried items.** The handoff applies broadcast to every item, but an anonymous forum post does not get TV coverage. Official and outlet events and price headlines are broadcast on their first tick, and broadcast reaches people whether or not they are on social media that tick.
- **2026-11-24 · #6 · `exposure_scale = 4` (new PLACEHOLDER) multiplies every layer's reach.** With the handoff's reach values the network is subcritical: a salient anonymous rumour reached ~20 of 10,000 agents even with 2.5× the online rate and 4× the share lifetime. #6's acceptance criterion requires an S-curve. Scanning reach × {2, 4, 6} and base_share {0.25, 0.5} at salience 0.7 vs 0.3 (5 runs each), ×4 with the user's base_share 0.25 was the first setting where a salient rumour often goes viral (3 of 5 runs, 12–24% of agents, S-shaped) while a weak one mostly fizzles. One global knob keeps the user's per-platform `reach` ratios intact and gives calibration (#12) a single parameter to fit.
- **2026-11-24 · #6 · Online rate comes from the diffusion config.** `Population.online_prob(hour, base_online)` takes the rate as an argument, so diffusion can use its own config (the population used to read its own copy).
- **2026-11-24 · #6 · Diffusion works on sparse (item, agent, exposure) triples.** Layers gained `receivers(sharers)`, and the dense `push` is now its bincount. Measured with one official event spreading over a day: 0.2 ms per tick at 10k agents (36% reached) and 2.4 ms at 100k (38%), so cost is linear in N and reach does not depend on N.
- **2026-11-24 · #6 · Talking your book** = the agent holds shares and the item is bullish (v1 has no short positions). The handoff's #10 wording ("profitable holders") is not applied yet: it needs the current price, which diffusion does not receive.
- **2026-11-24 · #6 · TikTok popularity** = the number of current sharers who use TikTok; with none, the item gets no algorithmic exposure.
- **2026-11-24 · #7 · Trust enters credibility.** `cred_eff = (credibility · trust)^(1 + 2·knowledge)`, where trust is the exposure-weighted trust of the layers that delivered the item that tick (TV / push alerts count as 1.0, as do seeds who hear an event first-hand). The handoff stores a `trust` per platform "for beliefs" but gives no formula; this keeps the user's exponent and makes a friend's post count for more than a stranger's tweet.
- **2026-11-24 · #7 · Denials end narratives.** A belief-moving item that is not a narrative but belongs to the same family as an agent's held narrative (e.g. the official denial hanging under the rumour) clears `held_narrative` and pulls `narrative_bias` toward the denial. Without it, holders keep being pulled toward a rumour after it has been officially denied.
- **2026-11-24 · #7 · Adopting moves `narrative_bias` halfway** toward the item's sentiment (`adopt_step = 0.5`, new PLACEHOLDER). With several adoptable items in one tick, one per agent is taken.
- **2026-11-24 · #7 · Mutations and inventions carry no true impact.** A distorted or made-up story says nothing new about the company, so it never moves perceived value. A mutation's salience is ×1.2 of the parent's *current* (decayed) salience; the mutators' shares of the parent are withdrawn and they seed the child.
- **2026-11-24 · #7 · "Without an explanation"** = the agent knows no item born in the last day whose sentiment points the same way as the move. Inventions get sentiment ±clip(0.4·|ret|/threshold, 0.3, 1), credibility `invent_credibility = 0.25` and salience `invent_salience = 0.6` (new PLACEHOLDERs).
- **2026-11-24 · #7 · Media outlets hold no beliefs.** Their confidence stays 0 and they never adopt, mutate or invent.

## Simplifications

_(none yet)_

## xfails

_(none yet)_

## Results

### Parameter-recovery test (#12)

_(pending)_

### Benchmarks (#15)

_(pending)_
