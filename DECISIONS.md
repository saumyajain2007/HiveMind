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

## Simplifications

_(none yet)_

## xfails

_(none yet)_

## Results

### Parameter-recovery test (#12)

_(pending)_

### Benchmarks (#15)

_(pending)_
