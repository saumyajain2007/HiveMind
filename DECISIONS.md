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
- **2026-11-24 · #9 · Position sizing uses current equity** (cash + shares × price), not the initial `wealth` trait, so winners and losers size differently as a run goes on. Buys are capped by cash at the limit price and sells by holdings: no leverage and no shorting for retail. A panicking holder sells even if the order is below the threshold.
- **2026-11-24 · #9 · Strategy fitness is shared by all investors.** One fitness per strategy, an EMA (`fitness_decay = 0.97`, new PLACEHOLDER) of sign(mean investor signal at t−1) · return at t. Weights therefore differ only through the category priors, as the handoff's formula implies.
- **2026-11-24 · #9 · Firms can be short; retail cannot.** Props: target = capital · tanh(k·1-hour momentum + k2·last tick's retail order imbalance), limits ±0.3%. Funds: target = capital · clip(k·(V_known − P)/P, ±1), limits ±1%. Firms only trade when the order is worth more than 1% of capital. Each firm type gets half of `firm_capital_share` × total investor wealth. New PLACEHOLDERs: `prop_momentum_ticks = 4`, `prop_momentum_k = 100`, `prop_imbalance_k = 1`, `fund_value_k = 5`, and `fund_lag_ticks = 96` (the handoff's 1-day lag).
- **2026-11-24 · #9 · Funds read official real events at once** (the handoff's "firms also learn immediately"): V_known is V_true one day ago plus the true impact of official events since then. Leaks and rumours reach funds only through the lag.
- **2026-11-24 · #9 · `DiscretionaryPolicy.on_event` returns a target fraction** that overrides a fund's rule for the rest of the trading day, or None. The default policy returns None; the LLM hook is a docstring only, as the handoff asks.
- **2026-11-24 · #10 · The market maker's ADV tracks traded volume.** It starts at `adv_turnover` × shares held, as the handoff says, then follows an EWMA of the volume actually traded (`adv_ewma = 0.97` per open tick, new PLACEHOLDER). With the fixed ADV (≈12k shares/day at 10k agents) the simulated traders sent ≈80k shares of retail orders and ≈470k of firm orders *per tick*, so per-tick moves were ~1–1.5% (≈6% daily vol, prices swinging ±15% a day). With the EWMA, per-tick sd is ≈0.3% (≈1.5% daily, close to the 1.9% implied by IV 30%). ADV means *average daily volume*, so measuring it from the market keeps the square-root law self-consistent however much the agents churn.
- **2026-11-24 · #10 · The market maker re-quotes on public news.** Real events seeded `official` or `outlet` shift its quotes at the next auction by `mm_news_pass_through` × true_impact (new PLACEHOLDER, 1.0): it supplies `mm_supply(r − shift)`, so agents' demand still decides where the price ends up. Without it, informed selling was absorbed by the market maker: a −33% fundamental shock moved the price ~3%. Leaks, insider tips and rumours do not shift quotes; they reach the price only through orders.
- **2026-11-24 · #10 · Prop firms toned down** (`prop_momentum_k` 100 → 30, `prop_imbalance_k` 1 → 0.2). Order imbalance flips sign from tick to tick, and with k2 = 1 the props swung between ±50% of capital every tick, which was most of the order flow.
- **2026-11-24 · #10 · Profitable holders talk their book.** Now that diffusion is given the price each tick, "talking your book" requires entry price ≤ current price (resolves the #6 note).
- **2026-11-24 · #10 · Seeds and RNG streams.** `config.seed` builds the world (population; graph with `[seed, 1]`). The run's `seed` spawns five independent streams (diffusion, beliefs, trading, market noise, event seeding) via `SeedSequence([seed, 7])`. `Simulation(world=...)` deep-copies the population, so one world serves many Monte Carlo runs. Same seed → identical arrays and JSON (tested).
- **2026-11-24 · #10 · Metrics layout.** Per-tick series (price, V_true, volume, mean investor confidence, IV, ATM call, market-maker inventory, retail order imbalance, online count, active items); awareness as `(tick, item, aware)` rows for active items; family awareness as `(tick, root, total, 6 platform-user counts, 5 category counts)` rows for families with an active item. `save` writes `metrics.npz` plus `lineage/events/summary/meta.json`; `load` reads them back.
- **2026-11-24 · #10 · TickFrame** = the web app's `tick` message fields plus `mm_inventory`, `imbalance`, `born` (event / narrative messages born this tick; events carry their `item` id) and, with a node sample, `node_seen` ([sample index, item id] pairs newly aware). Measured on the 5-day demo at 10k: frames add 1.7% runtime; frames plus a 3.4k-node sample add 9.9%.
- **2026-11-24 · #10 · Price headlines** have credibility 0.9, salience clip(0.4 + 5·|ret|), complexity 0.1 and a label like "Stock down 4.3%"; they are queued for the next tick.
- **2026-11-24 · #11 · Investors start at their target position.** `Trading.equilibrate` sets every investor's holding to what the trading rule wants at the opening price (entry price = that price). The handoff's "long-term investors start with an initial position" (50% of wealth) was far from the rule's target, so the first open replayed the whole set-up as one wave of selling (−4% before any news). Without events, day-1 closes now centre on the start price.
- **2026-11-24 · #11 · Demo timing.** Day 1 = the first simulated day (ticks 0–95). Rumour at 11:00 on day 1, denial (official, `parent` = rumour) at 10:00 on day 3, earnings miss −5% at 07:30 on day 4 (pre-market, so it gaps at the open). The scenario lives in `marketsim/scenarios.py` with the Builder's other presets (quiet market, meme squeeze).
- **2026-11-24 · #11 · Monte Carlo reuses one world.** `montecarlo.run` builds the population and graph once from `config.seed`; runs use dynamics seeds 1..R. With `workers > 1` each worker process builds the same world once (deterministic), and results are identical to a serial run (tested). The representative run kept for the awareness and lineage plots is the one with the median final price.
- **2026-11-24 · #11 · Stylised facts pool open-tick returns across runs** (kurtosis on the pooled sample, ACF averaged over runs). At 10k × 20 runs the demo reports excess kurtosis ≈ 59, dominated by the earnings gap, and |r| ACF at lag 1 ≈ 0.03 (little volatility clustering). Returns show positive ACF at lags 1–2 (≈0.2): order flow is persistent because agents come online gradually. Reported, not asserted (HANDOFF §4 M6); calibration (#12) is where this should be addressed.
- **2026-11-24 · #11 · Plot colours** come from the web app's light theme (validated in #19). Families use the six categorical hues in a fixed order by family id, so a family keeps its colour across plots; extra families are grey. Lines also differ by dash style and lineage markers by shape (origin).
- **2026-11-24 · #12 · Common random numbers in calibration.** Every trial runs the same dynamics seeds (1..`runs_per_trial`) on one world, so trial-to-trial differences come from the parameters. Search is uniform random inside the given ranges, as the handoff specifies. Parameter names are the handoff's four (`impact_Y`, `base_share`, `mu0`, `sentiment_scale`) or any `section.field`.
- **2026-11-24 · #12 · Identifiability is judged two ways:** the error as a share of the search range (recovered if ≤ 15%), and the Spearman rank correlation between each parameter and the trial RMSE (|ρ| < 0.2 = weakly identified: the objective barely depends on it).
- **2026-11-24 · #13 · How a daily series meets a tick simulation.** For each origin the simulation starts `lookback_days = 3` days earlier, so recent events can spread before the forecast starts; events are placed at their day and time. The model's forecast is the simulated return from the origin's close to the close `horizon` days later, applied to the actual origin close. Implied vol is set to the trailing 20-day realised vol at the origin, so both models use the same (backward-looking) volatility. Events used for each origin are recorded in the result, and a test shows a later event leaves earlier forecasts byte-identical.
- **2026-11-24 · #13 · The random walk is driftless and mean-preserving:** p0 · exp(N(−½σ²h, σ²h)) with the same trailing vol. On the synthetic demo series (40 days, 6 news jumps, 3,000 agents, 8 runs per origin) the model's mean CRPS is 1.73 against 1.52 for the random walk (skill −0.14): with no knowledge of news inside the horizon, the model adds narrative noise without information. This is a baseline, not a fitted result.
- **2026-11-24 · #17 · One result queue, one dispatcher thread.** Workers (a spawn-context `ProcessPoolExecutor`, `MARKETSIM_MAX_JOBS` = 2 by default) put `(run_id, kind, payload)` on a `multiprocessing.Manager` queue; one daemon thread in the API process appends each message to the run's in-memory channel and updates the run index. Cancellation is a Manager `Event` polled by `should_stop()` before every tick (Monte Carlo: between runs). A run still waiting in the pool is cancelled without starting. `MARKETSIM_EXECUTOR=thread` swaps in threads; `MARKETSIM_RUN_JOBS=0` records runs without running them (the #16 index tests use it).
- **2026-11-24 · #17 · The worker sends every tick; coalescing is per client.** Each WebSocket client reads the channel from its own position at most 20 times a second. A flush keeps every event / narrative message, the last tick of every simulated hour it covers and the newest tick, and only the newest Monte Carlo progress. So a slow client never holds up the worker, and every client gets at least one frame per simulated hour (tested with a real process pool: 24 hourly frames for a 1-day run).
- **2026-11-24 · #17 · `pace` for live viewing.** A 5-day run at 10k agents takes under a second, which is too fast to watch. `POST /runs` takes `pace` (ticks per second, 0 = as fast as possible); the worker sleeps to keep to it. It never changes results and is not part of `spec_hash`. The web demo button uses 48 ticks/s (about 10 s for 5 days).
- **2026-11-24 · #17 · Replays.** The last 32 finished channels stay in memory. Older or pre-restart single runs are replayed from `runs/<id>/result/` with every tick (not coalesced), so the Cockpit can scrub them. Runs left `queued` or `running` when the API stopped are marked `failed` ("interrupted") at startup.
- **2026-11-24 · #17 · Stream messages gained fields** the web types now declare: hello `mode`, `runs`, `n_nodes`, `node_sample` (3,000 sampled node ids for the network view), `replay`; tick `mm_inventory`, `imbalance`, `node_seen`; event `item`, `parent`, `salience`, `true_impact`; done `status`; and a new `progress` message for Monte Carlo (`done`, `total`, partial quantiles).
- **2026-11-24 · #17 · Monte Carlo inside a job** uses the run's `workers` for its own process pool (pool workers are not daemonic, so they may start children); with `workers = 1` it reuses the world already built in the job process.
- **2026-11-24 · #18 · Calibrations and backtests are runs.** They share the run index (modes `calibration` / `backtest`), the job pool, `POST /runs/{id}/cancel` and the live stream (one `trial` / `origin` message per step, never coalesced away). The dataset is copied into the run folder and its sha256 is in the spec, so deleting or re-uploading a dataset never changes a past result.
- **2026-11-24 · #18 · Calibrating on daily closes.** `calibrate` gained `observed_ticks` (one observation per day at the last open tick) and `relative` (both paths measured from their first value), because a real series is daily and at its own price level while the simulation is per tick and starts at 100.
- **2026-11-24 · #18 · Uploads are JSON, not multipart.** `POST /data/upload` takes the CSV as text plus the events list, so no `python-multipart` dependency; the web app reads the file and posts its text.
- **2026-11-24 · #18 · Gzip and packed arrays instead of orjson.** Responses over 1 kB are gzipped, and `?encoding=b64` sends large float arrays as little-endian float32 base64 (`{"dtype", "shape", "b64"}`), which shrinks them more than a faster JSON encoder would. orjson was not added.
- **2026-11-24 · #18 · `/graph` uses the run's streamed node sample** (3,000 nodes chosen from the world seed), so node indices match `tick.node_seen` and `/node-seen`. The world is rebuilt from the spec (deterministic) and the last two are cached. Reddit co-membership is drawn as a ring through each subreddit's sampled members rather than a clique; TikTok has no edges.
- **2026-11-24 · #18 · LLM provider.** `MARKETSIM_LLM_PROVIDER` is `none` by default (the endpoint returns prompts for a person to paste into any LLM, then validates the posted replies). `anthropic` uses the official `anthropic` SDK (optional `llm` extra) with `claude-opus-5-5` at `low` effort. Current Claude models reject `temperature`, so the handoff's "temperature 0" is replaced by the parser's response cache for repeatability. Server-side refusal fallbacks (`fallbacks: "default"`) are on; a refusal that survives them is reported as a 502 for that request.
- **2026-11-24 · #18 · Results meta** now records the size of each category and each platform's user count, so shares in the awareness heat-map can be computed without rebuilding the population.
- **2026-11-24 · #20 · Charts are a small in-house SVG kit** (`web/src/components/charts`: XY chart with bands, markers and a keyboard crosshair; grouped bars; heat map; legend) instead of ECharts. It uses the validated design tokens directly, follows the dataviz rules (one y axis, thin marks, legend for two or more series, values in text tokens, a tooltip on hover and ← → keys), and adds no megabyte-sized dependency. `lightweight-charts` (candles) and Sigma.js (network) are still used where a canvas or WebGL renderer pays off.
- **2026-11-24 · #20 · Mock results are real engine output.** `python -m marketsim_api.export_fixtures` runs a demo single run (3k agents), a Monte Carlo run (2k × 20), a calibration and a backtest through the API and saves each result endpoint's JSON under `web/src/mocks/fixtures/results/`. MSW serves them for any run id, so every page shows genuine model output in development and in the e2e suite without a backend. The fixtures are not regenerated in CI (about two minutes).
- **2026-11-24 · #20 · Builder state lives in a persisted Zustand store** (`marketsim-builder` in localStorage), so the Runs library can later "duplicate into the Builder" and a reload keeps the work. Client-side validation mirrors the API's `ScenarioSpec` checks (ticks inside the run, parents earlier, ranges) and blocks the run buttons with inline messages; server errors are still shown as toasts.
- **2026-11-24 · #20 · "Run live" uses pace 48 ticks/s** and opens the Cockpit; "Monte Carlo ×R" uses 2 workers and opens the Monte Carlo view. The Hawkes generator in the browser mirrors `events.hawkes_events` (same kinds, weights and attribute rules), and refuses explosive settings (branching ratio ≥ 1). The headline importer accepts an optional `day HH:MM |` prefix per line.
- **2026-11-24 · #21 · The candle chart shows market hours only.** Each 15-minute tick is one candle (open = the previous tick's price, close = this tick's); overnight ticks have no trades, so they are left out and the gaps between sessions mark the closed market (as on real intraday charts). Events outside market hours are marked on the next open candle. The axis uses the sim clock ("Day N", HH:MM) on a fixed fake calendar.
- **2026-11-24 · #21 · Playback reads the ring buffers.** "Pause" and the scrub slider move a cursor over the frames already received; every panel (chart, gauge, feed, awareness, stats) is computed at the cursor, so scrubbing never touches the network. "Live" returns to following the stream. "Replay with same seed" posts the run's own spec again (equal `spec_hash`, identical results).
- **2026-11-24 · #21 · The live store keeps every born item and each item's awareness history** outside React state (for the markers, the feed at any cursor position and the top-5 awareness chart). The feed shows the newest 60 items; colours in the awareness chart follow an item's birth order, so an item keeps its colour as the ranking changes.
- **2026-11-24 · #22 · The Monte Carlo view follows a running job over its stream**, drawing the fan from each `progress` message's partial quantiles, then switches to the stored `/quantiles` when the job is done. The terminal-price histogram uses every run's final price (`/paths?every=96`, which now always ends on the final tick), with a kernel density and the driftless random-walk benchmark (same implied vol, mean-preserving lognormal). "Mean CRPS" stays empty until a backtest is linked (#25). PNG / SVG export inlines the theme's computed colours into a standalone copy of the chart's SVG.
- **2026-11-24 · #23 · Network nodes are coloured by the story, not by confidence.** Per-agent confidence over time is not stored (a 3,000 × T matrix per run); the spread of a chosen item family (from `node_seen`) is what the view animates. Nodes are grey until they first see the family, then violet (narratives) or amber (official / news), drawn white and larger for the hour after; edges take their platform's colour and glow when either end just saw it. Category, traits and platforms are in the hover card. Platform colours appear only on edges, so they never share a mark with the semantic colours (DECISIONS #19).
- **2026-11-24 · #23 · Layout: ForceAtlas2 (LinLog) in a Web Worker on all layers' edges for 3.5 s**, then cached per run in localStorage, so switching layers keeps positions and a revisit is instant. Layers are switched by hiding edges. The view follows the Cockpit's clock when the same run is live there, and has its own play / scrub otherwise. An e2e test recounts the sampled nodes that saw the story from `/graph`, `/node-seen` and `/lineage` and checks the page shows the same number.
- **2026-11-24 · #24 · `/awareness` also returns each item's own curve** (`items`: item id → [tick, aware] rows while active), so the Narratives item card can show how many agents saw an item over time. "Sharers over time" is shown as that awareness curve plus the item's total shares; per-tick share counts are not stored.
- **2026-11-24 · #24 · Narrative colours follow the family root**, in the fixed categorical order by root id (price headlines grey and hidden by default), and the same colour marks a family in the story strip, the lineage, the curves and the heat map. The heat map shows each family's peak share aware within each investor category and among each platform's users (columns for platforms with users); an e2e test recomputes a cell from `/awareness`. The story strip is generated from the lineage, e.g. "Rumour #0 … → mutated twice → reached 41% of agents → official statement #5 reached 32% on its own".
- **2026-11-24 · fix · `.gitignore` patterns `runs/` and `outputs/` are anchored to the repo root.** Unanchored, `runs/` also ignored `web/src/features/runs/`, which broke CI for #22–#23.
- **2026-11-24 · #25 · Deployment is Docker Compose with two containers:** `api` (python:3.12-slim + uv, uvicorn, results in a named volume) and `web` (Vite build served by Caddy, which also reverse-proxies `/api` including the WebSocket, with a client-side-route fallback). The app is on :8080. Docker could not be run on the dev machine at the time, so a CI `docker` job builds and starts the stack and checks the app, a client-side route and a real run through Caddy. A Makefile wraps dev / up / test / e2e / fixtures / demo.
- **2026-11-24 · #25 · Visual-regression snapshots are opt-in** (`VISUAL=1`). Screenshots differ between Windows (dev) and Linux (CI) fonts and anti-aliasing, so committed baselines from one would always fail on the other; the functional e2e suite (29 tests, axe on every page and flow) is what CI enforces. The end-to-end flow test builds the demo, runs it live, checks the event markers, runs Monte Carlo, checks the fan and opens the lineage.
- **2026-11-24 · #25 · The Analysis page shows the recovery-test result from DECISIONS** (it is a one-minute engine run, not a per-user job) next to live calibrations and backtests. Uploads read the files in the browser and post their text (#18). Calibrations and backtests are listed by mode from the run index.
- **2026-11-24 · #25 · Run summaries carry daily closes** (`price_spark`) and, for Monte Carlo, the median final price and return, so the run library shows the same sparkline and final move for real and mock runs.
- **2026-11-24 · #25 · e2e reliability.** Waits use page load plus a content locator instead of `networkidle` (pages poll), assertions allow 10 s, axe runs after animations settle, and local runs use at most 6 workers against the single Vite dev server.
- **2026-11-24 · notes gaps · Platform boost.** Items compete for an agent's attention slots on exposure × salience × platform boost, where the boost is the exposure-weighted `graph.attention_boost` of the layers that delivered the item (new PLACEHOLDER: friendship 1.2, TikTok 1.1, others 1.0; TV / push alerts 1.0). It only reorders the competition; whether an item is seen at all still follows p_see.
- **2026-11-24 · notes gaps · Outrage.** Sharing gains `outrage_weight · max(−sentiment × confidence, 0)` (new PLACEHOLDER 0.3, against 0.8 for agreement), so an item that contradicts an agent's view can also be shared, as the notes say ("agreement (or outrage)").
- **2026-11-24 · notes gaps · Connections are stored per agent** (`Population.connections`: followers on directed layers + friends), set when the world is built and used to pick insiders.
- **2026-11-24 · notes gaps · The company is an agent.** `firms.Company` runs a buyback programme: it knows its own value at once and buys back (never sells) when the price is more than `company_buyback_threshold` (8%) below it, spending at most `company_buyback_daily` (10%) of its programme (2% of investor wealth) per day; bought shares are retired. All new PLACEHOLDERs.
- **2026-11-24 · notes gaps · The `[TBD]` agent field stays out:** the notes never say what it is.

## Simplifications

_(none yet)_

## xfails

_(none yet)_

## Results

### Parameter-recovery test (#12)

`python -m marketsim.calibration [observed_runs]`: demo scenario, 5,000 agents, 5 days, true parameters at the middle of each range, 40 random trials × 4 dynamics seeds, RMSE on the median log-price path.

**Observed = one simulated path** (what calibrating on real history looks like):

| parameter | range | true | recovered | error (% of range) | rank corr. with RMSE | verdict |
|---|---|---|---|---|---|---|
| `impact_Y` | 0.3–1.5 | 0.9 | 1.33 | 35% | +0.16 | not recovered, weakly identified |
| `base_share` | 0.1–0.5 | 0.3 | 0.125 | 44% | −0.15 | not recovered, weakly identified |
| `mu0` | 0.1–0.7 | 0.4 | 0.39 | 2% | +0.10 | recovered (by luck), weakly identified |
| `sentiment_scale` | 0.01–0.10 | 0.055 | 0.084 | 33% | −0.29 | not recovered |

Best RMSE 0.0119 vs 0.0180 at the true parameters: the search fits the noise of the single observed path better than the truth does.

**Observed = median of 8 paths** (a noise-free target):

| parameter | true | recovered | error (% of range) | rank corr. with RMSE | verdict |
|---|---|---|---|---|---|
| `impact_Y` | 0.9 | 0.701 | 17% | +0.39 | not recovered (closest) |
| `base_share` | 0.3 | 0.348 | 12% | +0.13 | recovered, weakly identified |
| `mu0` | 0.4 | 0.145 | 42% | −0.09 | not recovered, weakly identified |
| `sentiment_scale` | 0.055 | 0.033 | 24% | +0.08 | not recovered, weakly identified |

Best RMSE 0.0040 vs 0.0078 at the true parameters.

**Conclusion.** One 5-day price path does not identify these four parameters. `impact_Y` carries the most signal (it scales every move); `mu0` and `sentiment_scale` barely change the median path, because belief steps and the sentiment term are small next to the fundamental and momentum terms and the public-news re-quote; `base_share` mainly changes *who* hears a rumour, which the price shows only weakly. Before trusting calibrated values: fit to many events (or several stocks) at once, add awareness or volume targets alongside price, and fix the non-identified parameters from outside data (survey or platform data in DATA_SOURCES.md) rather than fitting them.

### Benchmarks (#15)

`uv run python benchmarks/bench.py --sizes 10000 100000 1000000` (each size in its own process; demo scenario for one day; Windows 11 dev machine, 32 threads, ~2 GB RAM free at the time):

| agents | degrees | edges | build | s / tick (mean) | s / tick (open) | peak RSS |
|---:|---|---:|---:|---:|---:|---:|
| 10,000 | default | 160,442 | 0.2 s | 0.0005 | 0.0012 | 75 MB |
| 100,000 | default | 1,756,497 | 2.2 s | 0.0030 | 0.0044 | 209 MB |
| 1,000,000 | halved | 9,242,273 | 22 s | 0.055 | 0.060 | 1.0 GB |
| 1,000,000 | default | 17,664,579 | 32 s | 0.24 | 0.096 | 1.9 GB |

The 100k target (< 0.5 s per tick) is met with a wide margin. "Halved" halves every layer's mean degree / memberships; the default degrees also fit in memory, so both are listed.

**Profile at 1M (default degrees, one day, 23.5 s):** (1) `Diffusion._absorb`, 8.3 s: sorting and de-duplicating the (item, agent) exposure triples; (2) gathering receivers from the graph CSRs (`gather_rows` + `np.repeat`), ~5.5 s; (3) the online mask (`online_prob` + mask), 2.1 s. The easy win taken: the investor mask used during market hours is now cached instead of rebuilt every tick. The rest is already vectorised; the big lever is fewer items (next point).

**At 1M a viral rumour mutates almost every tick.** The handoff's rule gives every sharer of a narrative a chance to mutate, with at most one child per parent per tick. With thousands of sharers per tick the cap binds every tick: 247 mutations in one day, and 122 items evicted from the 128-slot store. Kept as specified; v2 should make mutation a per-item rate.

### Real stock, real events: the AAPL experiment

`scripts/fetch_market_data.py AAPL` (one-off, network) → `data/AAPL/`; `python -m marketsim.experiment AAPL` (offline) → `docs/experiments/AAPL/` and the web app's **Real data** page.

**Data.** Adjusted daily closes for AAPL and SPY from Yahoo's chart API; every 8-K, 8-K/A, 10-Q and 10-K from SEC EDGAR's submissions API, with item codes and the exact acceptance time; quarterly diluted EPS and revenue from SEC XBRL `companyfacts`. Requests send a generic User-Agent, nothing personal. The engine never calls the network.

**Event timing.** EDGAR's `acceptanceDateTime` is UTC (an earnings release at 16:30 New York shows as 21:30 or 20:30), so times are converted to New York with the US DST rules. A filing accepted before 16:00 on a trading day is reflected in that day's close, otherwise in the next close.

**Labels.** Market-model event study against SPY (120-day estimation window), abnormal log return on the reaction day only, window (0, 0). Labels are training and scoring targets, never forecast inputs.

**Earnings own their reaction day.** Apple files a 10-Q (and often other 8-Ks) within days of its earnings 8-K. When several filings share a reaction day with an earnings release, only the release is a training example; otherwise the 10-Q "learns" the earnings move.

**Impact model ("classification model or something").** Multinomial logistic regression with L2 on three classes (down < −1%, flat, up > +1% abnormal return), plus ridge regression on log |abnormal return| with a lognormal residual. Features known at the announcement: the filing group (8 groups from item codes), release after the close, 5- and 20-day stock return, 5-day market return, 20-day realised volatility, volume ratio and, for earnings only, year-on-year growth of the reported EPS and revenue. L2 is picked on the last 30% of the training years. Size is the predictable part (Apple's earnings move the stock about 4× more than other filings); direction is close to a coin flip, as it should be for a liquid large cap.

**Forecasters** (each gives a distribution of the close h days ahead, scored by CRPS against a random walk):

1. *Random walk*: lognormal with the trailing 20-day volatility.
2. *Event-aware random walk*: the same, plus a jump drawn from the impact model for every scheduled earnings release inside the horizon.
3. *Agent model, raw*: the simulation is started 5 trading days before the origin. The filings from that warm-up are injected at the impact model's expected reaction. Scheduled earnings in the horizon are injected with a reaction sampled from the impact model in each run; the release's numbers aren't known in advance, so EPS and revenue growth are masked. The R runs become a predictive distribution with the small-sample Student-t rule.
4. *Agent model, recalibrated*: the same runs after a correction fitted on training origins only. The forecast log return is Normal(shrink × ensemble mean, sqrt((spread × ensemble sd)² + (w × trailing vol)²)), with the parameters fitted by minimum CRPS. This is the standard "model output statistics" step of ensemble weather forecasting.
5. *Agent model, oracle*: the raw model, but every event in the horizon (scheduled or not) is injected with its true reaction. This leaks the future on purpose. It is an upper bound on what better event prediction could buy, not a forecaster.

**Scoring ensembles fairly.** The first full run scored the agent model's 10 runs directly against a random walk scored on 4,000 samples, and that comparison is biased in two ways. The 5–95% interval of 10 draws contains a new draw only about 80% of the time, however good the model. The sample CRPS of an R-member ensemble is also inflated by about E|X − X'| / (2R), about 10% of the score at R = 10. That penalty grows with the spread, so the parameter grid preferred the narrowest ensemble. This was most of that run's "−9.5% skill, 71% coverage". Every forecaster is now scored on the same number of samples drawn from its predictive distribution.

**Earnings jump scale.** The impact model's size distribution is fitted on all filings. A single scale on its sampled earnings jumps is chosen by the event-aware random walk's one-day CRPS over every training-period earnings release (33 of them), and it applies to both the event-aware random walk and the agent model.

Only earnings count as scheduled (their dates are public weeks ahead); every other filing reaches a forecaster only after it happens. `tests/test_realdata.py` checks this.

**Training the simulation.** A grid over `market.noise_frac` × `market.mm_news_pass_through`, scored by the raw ensemble's mean one-day CRPS on 200 training origins drawn at random from 2016–2023. The recalibration is then fitted per horizon on the same origins. An earlier version took the training origins around events only. That over-represented pre-earnings days and picked too little noise, so the agent model's 90% band covered only 57% of outcomes. Random origins fixed it.

**Not fitted to data, still PLACEHOLDER:** the population (wealth, archetype mix, confidence) and the social graph (degrees, platform mix, trust). The experiment fits only the market-level noise and news pass-through. An agent-level fit needs survey and platform data (see DATA_SOURCES.md), not a price series.

**All six platforms on by default.** The design notes list Twitter, Reddit, friendship, Instagram, TikTok and YouTube, and all are now built by default (`graph.platforms`); turn some off to compare. Platform `attention_boost` (friendship 1.2, TikTok 1.1, others 1.0) and `diffusion.outrage_weight` (0.3) are PLACEHOLDER.

### Fitting the agents to AAPL (`marketsim.agent_fit`)

Method of simulated moments on the training years only. Twelve quarter-long windows (63 trading days) are drawn at random from 2016–2023. Each window is replayed in the simulation with its real filings and their true reactions (training data, so this is allowed), and six moments of the simulated daily returns and volumes are compared with the real ones: return sd, excess kurtosis, lag-1 autocorrelation, mean |r| autocorrelation at lags 1–5, the earnings-day / other-day ratio of mean |r|, and the volume–|r| correlation. The distance is a sum of squared moment gaps, each scaled by roughly its sampling error. The search is a 48-point Latin hypercube plus the defaults; the 4 best are re-run with 2 fresh seeds and the lowest mean distance wins.

Fitted: `trading.sentiment_scale`, `trading.switching`, `trading.risk_aversion`, `market.firm_capital_share`, `market.prop_momentum_k`, `market.fund_value_k`, `diffusion.base_share`, `market.noise_frac`. These are read at run time. The population (wealth, archetype mix, demographics) and the social graph are **not** fitted: a price series cannot identify them.

| moment | real | defaults | fitted |
|---|---|---|---|
| daily sd | 2.31% | 0.92% | 1.43% |
| excess kurtosis | 7.9 | 14.5 | 6.0 |
| lag-1 autocorrelation | −0.059 | −0.037 | −0.054 |
| \|r\| autocorrelation, lags 1–5 | 0.096 | 0.125 | 0.090 |
| earnings-day / other-day \|r\| | 2.3 | 9.0 | 5.0 |
| volume–\|r\| correlation | 0.60 | 0.36 | 0.41 |

Distance 77.5 → 23.7. Over the search, only `market.noise_frac` (rank correlation with the distance +0.32) and `market.prop_momentum_k` (−0.26) are clearly identified; the other six change the distance little. Three fitted values sit near the edge of their box (`sentiment_scale` 0.14 of 0.15, `fund_value_k` 14.3 of 15, `prop_momentum_k` 72.6 of 80), so the box should be widened next time. The fitted agents still under-shoot daily volatility (the forecast grid then re-tunes `noise_frac` around the fitted value) and over-state earnings moves. `marketsim.experiment` applies `docs/experiments/<T>/agent_fit.json` to every simulation when it exists.

### Strategies on the forecasts (`marketsim.strategy`)

Daily, AAPL only. Positions are set at each close from that close's forecast and held to the next close, with 5 bp of cost per unit of position change. Rules are fixed in advance or set from the training years, never tuned on the test period (tuning on the period you report is how backtests lie):

- buy and hold;
- direction long/short (sign of the forecast centre);
- direction long/flat;
- volatility targeting to AAPL's 2016–2023 daily sd, with the model's forecast sd (capped at 1.5×);
- the same volatility targeting with trailing 20-day volatility (to see whether the model adds anything over a naive risk forecast);
- the earnings classifier (long or short on earnings reaction days only, by the sign of the expected reaction).

Each is reported with Sharpe, a stationary-bootstrap 95% CI and P(Sharpe ≤ buy and hold), drawdown, and alpha and beta against buy and hold. The page and `strategy.json` also carry the per-day forecast distribution (mean, sd, quantiles, P(up)) and the forecast statistics: bias, RMSE, information coefficient, z-scores, coverage, and volatility skill.

### Isolating the effect of individual events (the selling point)

**In the simulator (`marketsim.isolation`, run mode `isolation`, Event lab → Simulator).** For each seed the scenario runs once with every event, once with none, and once per event with only that event removed. Every subsystem draws from its own random stream (`SeedSequence([seed, 7]).spawn(5)`), so a run without an event is bit-identical to the full run until the moment the event would have fired; the API test checks that the effect path is exactly 0 before the event. Any later difference is the event's effect: directly through the market maker's re-quote, and through the agents who heard of it, shared it, changed beliefs and traded. Reported per event:

- the mean paired effect path with a 5–95% band and standard errors;
- the final effect with a 95% CI and P(effect > 0);
- the effect after one day, the peak, and the time to half of the peak;
- pass-through: effect / true impact;
- the extra volume the event caused;
- its share of the total move.

Reported for the whole scenario: **interaction**, the move with all events minus the sum of the isolated effects. It is not zero: in the demo, the denial partly cancels the rumour.

**Removing vs neutralising.** Removing an event means its children (mutations, inventions) also never happen, which is what "without this event" means. The alternative, keeping it with zero impact, would still spread a story and is a different counterfactual.

**On real moves (`python -m marketsim.isolation AAPL`, Event lab → Real earnings moves).** Each test-period earnings window, from the close before the release to two closes later, is replayed from five days earlier with its real filings at their measured reactions (fitted agents). Each filing's isolated contribution is set next to the real market-adjusted move. This is a model-based decomposition: it shows how the simulated market splits a move between filings, not a measurement of the split.

**Bug found by isolation: earnings and the 10-Q double-counted.** Apple files its 10-Q the morning after the earnings release, so both react on the same day, and both carried the same measured reaction as their label. The oracle replay injected the earnings move twice. That made the oracle look bad on earnings days (−22% skill), and the first decomposition showed the 10-Q "causing" as much as the earnings. Fix: an earnings release owns its reaction day in the replay too (`Experiment.task`, as it already did for training labels). The AAPL experiment was re-run with the fix.

### The event library (`marketsim.event_library`, Event lab → Event library)

`scripts/fetch_market_data.py` with no arguments now fetches a 50-stock universe across sectors; already-downloaded tickers are skipped. XOM returned only 8 filings from EDGAR's submissions API and is effectively missing; to look into.

9,881 filings (2015–2026) get the real-data isolation of an event type's effect. The abnormal return vs a market model on SPY (120-day estimation window) is compared with a *normal* day's abnormal move for the same stock: the residual sd × sqrt(2/π), the mean of a half-normal. |SAR| = mean |AR / residual sd| / sqrt(2/π), so 1 means "as big as an ordinary day". Results:

- **Earnings:** |SAR| 3.9, an excess |AR| of +3.0 points, and 41% of releases move the stock more than 3 sd. 80% of the 5-day move happens on day 0.
- **Reg FD disclosures (7.01):** |SAR| 1.3.
- **Every other type** (votes, executive changes, governance, agreements, 10-Q / 10-K, other 8.01 events): about 1, the size of an ordinary day.
- **Direction:** no event type has a reliable average direction (all |t| < 2).

The impact model trained on all stocks predicts the size of a reaction out of sample with correlation 0.53. Direction is 53% on 1,217 moves beyond ±1%. On the same test events, the pooled model's size correlation is 0.53, against 0.50 for a model trained only on each stock's own events.

### Real population data: US Census + Federal Reserve SCF (`population.survey = "us"`, default)

`uv run --with pandas python scripts/fetch_population_data.py` builds `data/population/us.json`. The Census API now requires a key, so age comes from the Census Bureau's keyless CSV of Vintage 2024 national estimates by single year of age (85+ spread over 85–95). Everything else comes from the Federal Reserve's Survey of Consumer Finances 2022 summary extract (22,975 records, survey-weighted).

| input | was (PLACEHOLDER) | now (data) |
|---|---|---|
| age | Beta on 18–85, median 43.9 | Census adults, median 46.8 |
| wealth (investable) | lognormal, median $50k, p90 $265k | SCF financial assets, median $40k, p90 ≈ $1.0M |
| knowledge | Beta(2, 4), median 0.31 | SCF self-rated 0–10 / 10, median 0.8 |
| investor share | 15% | 21.0%: households owning stocks directly (the Fed's published figure is 21%) |
| investor logit | wealth 1.0, knowledge 0.6, risk 0.4 | SCF weighted logistic: wealth 0.98, knowledge 0.16, risk 0.60 |
| correlations (age, wealth, knowledge, risk) | guesses | SCF on normal scores: age–wealth 0.22, age–knowledge 0.22, age–risk −0.19, wealth–knowledge 0.27, wealth–risk 0.36, knowledge–risk 0.09 |

Caveats:

- **Units and households.** SCF records are households, with the head's age, and dollars as given in the current extract: its median net worth is $210.9k, above the published $192.9k, so the extract is apparently in more recent dollars. Age itself comes from the Census.
- **Knowledge is self-rated** and probably overstates objective literacy (SCF `FINLIT`, a 3-question quiz, is the alternative).
- **Risk tolerance is coarse.** Its marginal stays PLACEHOLDER; only its correlations come from the SCF 3-level risk question.
- **Not covered.** Impulsiveness, belief tolerance, media attention, loss aversion, the investor-category mix, platform usage and the social graph keep their PLACEHOLDER values; these surveys do not measure them.

`survey = ""` restores the placeholders. A 1,000,000-agent demo run with this population (run `93cd05b5f7d5`, 5 days) produced:

- the rumour reaching 67% of agents, with 626 mutations;
- a price path of 108.1 → 108.8 → 103.4 → 99.1 → 99.7;
- 15-minute returns that are far too fat-tailed (excess kurtosis 42) and too autocorrelated (lag-1 0.31).

So the census population does not by itself make the tick dynamics realistic.

### Backtesting framework (`marketsim.backtester`)

A small framework instead of a third-party one (backtesting.py is AGPL; vectorbt and bt pull in heavy dependencies), so it can live inside the engine and the API. `Backtest(dates, returns, benchmark, costs).run_all(signals, n_trials=...)`.

- **Timing.** Positions are decided at close t and paid the t → t+1 return, so a signal never sees its own return.
- **Costs.** Commission plus slippage (default 1 + 4 bp) on every change of position, and a borrow fee on shorts (30 bp a year).
- **Statistics.** Sharpe with a stationary-bootstrap CI, Sortino, Calmar, max drawdown and its duration, per-trade win rate, profit factor and expectancy, alpha, beta and information ratio, skew and kurtosis.
- **Overfitting-aware ratios.** The **probabilistic Sharpe ratio** and the **deflated Sharpe ratio** (Bailey & López de Prado). The deflated version measures a Sharpe against the best one N skill-less variants would produce by luck. Pass the true number of variants tried, including discarded ones; otherwise it flatters the result.
- **Forecast fitness.** `forecast_fitness` scores the forecasts themselves: IC, rank IC, hit rate, Brier score and log loss against climatology, and calibration bins.

`marketsim.strategy` now runs its six pre-specified rules through it and reports fitness on the training origins and the test period. AAPL shows overfitting directly:

| fitness | 1-day IC | 5-day IC |
|---|---|---|
| training origins (in sample) | 0.27 | 0.26 |
| test period (out of sample) | −0.01 | −0.03 |

The recalibration was fitted on those very training origins. Deflated Sharpe over the 6 rules: buy and hold 0.38, volatility targeting 0.35, direction rules 0.00–0.02.

**On overfitting experiments (agreed scope).** Fitting the model hard to many custom events for one stock is fine as an experiment, as long as every result reports in-sample and out-of-sample side by side and the deflated Sharpe uses the real number of trials. Results are never fabricated or tuned on the test period.

### Tick dynamics fitted to real 15-minute bars (`marketsim.intraday_fit`)

The 1M-agent census run showed the market's tick dynamics were wrong: 15-minute returns with lag-1 autocorrelation +0.31 (real ≈ 0), excess kurtosis 42 (inflated by the demo's shocks) and weak volatility clustering. Stories also mutated almost every tick.

**Targets.** 59 days of real AAPL 15-minute bars (`fetch_market_data.py AAPL --intraday`, regular hours, overnight gaps excluded):

- lag-1 autocorrelation −0.009;
- |r| lag-1 autocorrelation 0.22;
- excess kurtosis 3.35;
- 15-min sd 0.21%;
- open-to-close variance ratio 0.67.

**What changed in the engine**

- **Mutation per capita** (`diffusion.mutate_ref_agents = 10,000`): above that size each sharer's mutation chance is scaled by 10,000 / N, so a popular story does not mutate every tick at 1M agents. It changes nothing at ≤ 10k agents.
- **Efficient market maker** (`market.mm_flow_anticipation`): agents hear news over hours, so the auction's impact x_t is persistent. The market maker estimates its persistence ρ online and prices in the predictable rest of the flow, so the return is x_t + k·ρ/(1−ρ)·(x_t − x_{t−1}); for k = 1 only the surprise moves the price. An earlier version that only scaled x_t up was wrong: it added noise without removing the autocorrelation, and was dropped.
- **Volatility feedback** (`market.noise_vol_feedback`): the unmodelled flow scales with recent intraday |r|, anchored to implied (not realised) volatility; the realised anchor ran away in testing.
- **Informed unmodelled flow** (`market.noise_permanence`): this share of the noise also moves V_true and every agent's perceived value. Without it, value investors trade noise straight back and intraday moves revert within the day.
- **Intraday volatility profile** (`market.noise_intraday_profile`): AAPL's measured U-shape, 2.0× at the open and 0.65–0.8× over lunch.
- **Background news.** Self-exciting synthetic events (`events.hawkes_events`, rate 0.0297 per tick ≈ 2.9 a day, impact sd 0.54%) are a *scenario* input. Without news every simulated day is alike, and neither the fat tails nor day-to-day volatility differences appear.

**Fit.** A 64-point Latin-hypercube search at 100,000 agents (3 seeds × 6 days). The 3 best candidates and 12 perturbations were then re-scored on 4 fresh seeds × 10 days, because the first pass is noisy once news adds fat tails. The chosen values are now the defaults:

| setting | was | fitted |
|---|---|---|
| `market.impact_Y` (how far the agents' own flow moves the price) | 0.7 | 0.099 |
| `market.noise_frac` | 0.3 | 0.729 |
| `market.noise_vol_feedback` | (new) | 0.239 |
| `market.prop_momentum_k` | 30 | 4.42 |
| `market.mm_flow_anticipation` | (new) | 0.6 (top of its range) |
| `market.noise_permanence` | (new) | 0.047 |

| 15-min moment | real AAPL | old defaults (quiet) | fitted (with news) |
|---|---|---|---|
| lag-1 autocorrelation | −0.009 | +0.43 | −0.009 |
| excess kurtosis | 3.35 | −0.98 | 3.48 |
| sd | 0.21% | 0.19% | 0.20% |
| \|r\| lag-1 autocorrelation | 0.22 | 0.21 | 0.11 |
| open-to-close variance ratio | 0.67 | 0.55 | 1.10 |
| intraday share of daily sd (not fitted: no overnight news) | 0.75 | 1.04 | 0.86 |

Distance 228 → 13.

**What it means.**

- **The agents' own flow is too persistent.** To make prices behave like AAPL's, that flow has to move the price about 7× less than before: most 15-minute variance comes from flow the model does not represent, plus news. Rumours with no real impact therefore move the simulated price much less than before.
- **Gaps that remain.** Volatility clustering is about half the real level, and the fitted market reverts less within the day than AAPL does.
- **Ranges and sources.** `mm_flow_anticipation` sits at the top of its range. All targets come from one stock over 59 days.

**Two bugs in the first version of these mechanisms, found while regenerating the results:**

1. **News amplified by the flow anticipation.** The auction's impact included the market maker's news re-quote, so the anticipation term treated a news jump as persistent flow and amplified it. Real earnings moves of −9% were simulated as −14%, and one of +0.7% came out as +8%. Fix: anticipation acts on the order-flow part only (impact − quote shift). `test_news_requote_is_not_amplified` pins it.
2. **Runaway volatility over weeks.** The noise level scaled with *realised* daily volatility while the volatility feedback raised realised volatility, an unbounded loop. In a 63-day replay (July–September 2018) the price went from 330 to 2,200 against a value of about 120, and that one window wrecked the agent fit (daily sd 5.3% vs real 2.3%, kurtosis 49). Fix: the noise level is anchored to implied volatility, and the anticipation gain is capped (`flow_rho_max = 0.6`, at most 3 noise sds a tick). `test_noise_cannot_run_away` pins it. All 12 agent-fit windows are now stable, with simulated daily sd 0.7–1.7% vs real 1.0–1.9% (the COVID windows are higher in reality, 4.4%).

The tick-dynamics fit was redone after fix 1. Search plus refinement chose no background news, and those values are the current defaults: `impact_Y` 0.122, `noise_frac` 0.897, `noise_vol_feedback` 0.258, `prop_momentum_k` 3.87, `mm_flow_anticipation` 0.556, `noise_permanence` 0.0685.

Re-checked after fix 2 (4 seeds × 10 days, 100k agents, distance 11.4):

| 15-min moment | real AAPL | fitted |
|---|---|---|
| lag-1 autocorrelation | −0.009 | −0.04 |
| \|r\| lag-1 autocorrelation | 0.22 | 0.10 |
| excess kurtosis | 3.35 | 1.0 |
| sd | 0.21% | 0.25% |
| open-to-close variance ratio | 0.67 | 0.67 |

Fat tails need news; the background-news process is still available as a scenario input.
