# HANDOFF: build `marketsim` v1 overnight

You are Claude Code picking up an in-progress build. Work through this file top to bottom without waiting for the user, who is asleep. When a decision isn't covered here, take the simplest option that fits the design, write it down in `DECISIONS.md`, and keep going. Stop only for something that can't be undone.

## 0. Ground rules

- **Source of truth for the design:** `docs/design_notes.txt`, the user's own notes. Don't rewrite or "improve" that file. This handoff records the decisions made in chat on top of those notes.
- **Git:** never commit or push to `main`. Work on a branch (`feat/marketsim-v1`) and leave it for a pull request. Do **not** add `Co-Authored-By` or `Claude-Session` trailers to commit messages. Commit after each milestone below with a plain message, e.g. `M2: diffusion and beliefs`.
- **Stack:** Python 3.11+, NumPy, SciPy, matplotlib, pytest. No PyTorch or Numba needed (add them only if they're already installed and you're optimising). Everything is vectorised over arrays, never one Python object per agent.
- **No network calls at runtime.** The LLM event parser takes a user-supplied callable and is exercised in tests with a fake.
- **Placeholders:** every number not fitted to data is marked `PLACEHOLDER` in `config.py`. Keep that convention for anything new.
- **Develop at 10k agents.** Only scale to 100k / 1M in the benchmark step.
- If you get stuck on one module for more than ~45 minutes, simplify it, note the simplification in `DECISIONS.md`, and move on. A complete, simple v1 beats a half-built clever one.

## 1. Scope of v1 (decided)

| Area | v1 decision |
|---|---|
| Stocks | One ticker |
| Platforms on by default | Twitter (directed), Reddit (membership), Friendship (undirected) |
| Platforms implemented but off | Instagram (directed), TikTok (algorithmic), YouTube (creator→subscriber + lag) |
| Population | Gaussian copula over traits + conditional sampling for categories |
| Market | Batch (call) auction per tick + market maker whose depth follows the square-root impact law |
| Options | Signal only: implied vol is an input; Black–Scholes ATM price is logged as state |
| Large agents | Rule-based: prop firms (momentum), funds (fundamental). Media outlets are special nodes in the graph |
| LLMs | Offline event parser only (callable injected). No per-agent or per-tick LLM calls. No RL |
| Nodes | Can be added during a run, never removed |
| Prediction | Monte Carlo price-path distribution, calibration (with a parameter-recovery test), backtest vs random walk using CRPS |

## 2. Answers to the open "???" / "!!!" in the notes (decided in chat)

1. **Correlation matrix / distributions:** Gaussian copula. Each trait has a fitted marginal; sample a multivariate normal with correlation R, map to uniforms with the normal CDF, then through each marginal's inverse CDF. Repair R to the nearest PSD matrix (eigenvalue clipping) before use. Categorical traits (participant category, platform use) are sampled *conditionally* on the continuous traits (multinomial logit / logistic).
2. **Organised trading firms / LLMs model prop firms:** separate firm agents, **rule-based** (prop = short-horizon momentum + order-imbalance; funds = fundamental value with a lag). Leave a `DiscretionaryPolicy` hook where an LLM could decide a fund's position *once per official event*. Don't implement an LLM call.
3. **YouTube:** creator→subscriber directed graph (creators ≈ top 1% influence among YouTube users), plus a production lag: a creator who decides to cover an item shares it 16–96 ticks later.
4. **Friendship:** undirected, built mostly inside offline communities, plus triadic closure. Higher `trust` weight than other layers.
5. **Twitter:** directed Chung–Lu like Instagram, but homophily is by **main interest topic** (so a finance cluster emerges), low reciprocity, fast decay.
6. **"HAS TO BE MODELLED BASED ON DATA":** generators are parameterised so their statistics (degree distribution, clustering, reciprocity) can be matched to published values. Write `graph.layer_stats()` to report them. Leave the fitting to data as a TODO with sources listed in `DATA_SOURCES.md` (SNAP datasets, Pew / Ofcom platform use by age, Arctic Shift for Reddit, since Pushshift access is restricted).
7. **LLM event parsing + "use reinforcement":** implement the parser (prompt template, JSON schema, range validation/clamping, temperature 0, cache to disk). **No RL in v1.** Add `abnormal_return_impact()` (event study) to label historical `true_impact` **for calibration only**, with a docstring warning that using it as a forecast input is lookahead leakage.
8. **Simple orderbook:** a batch auction replaces the `price × exp(λ…)` formula. Each tick: collect limit orders, find the price where agent excess demand equals what the market maker supplies, fill every crossing order at that one price, and let the market maker absorb the difference.
9. **"Predetermined values / black box / pretraining":** replaced by the square-root impact law. Market maker supply at log-move r is `sign(r) · ADV · (r / (Y · σ_daily))²`, with Y ≈ 0.7 by default and ADV and σ taken from the stock. One fitted constant, fully transparent.
10. **Options (Black–Scholes):** signal only in v1. Implied vol feeds agents' risk term; BS ATM call price is logged. Dealer gamma-hedging is v2.

## 3. Repository layout to build

```
marketsim/
  HANDOFF.md            (this file)
  DECISIONS.md          (create: every judgement call you make)
  DATA_SOURCES.md       (create: where each placeholder should come from)
  README.md             (create at the end)
  docs/design_notes.txt (user's notes, do not edit)
  marketsim/
    __init__.py
    config.py           (DONE; extend if needed, keep PLACEHOLDER markers)
    population.py       M1
    graph.py            M1
    events.py           M1
    items.py            M2  (active news/narrative items, awareness, lineage)
    diffusion.py        M2
    beliefs.py          M2  (belief update + adopt / mutate / invent)
    trading.py          M3
    firms.py            M3
    market.py           M3  (state, batch auction, Black-Scholes)
    sim.py              M4  (tick loop, metrics)
    montecarlo.py       M4
    calibration.py      M5
    backtest.py         M5
    event_parser.py     M5
    viz.py              M4
    run_demo.py         M4  (python -m marketsim.run_demo)
  tests/                one test file per module
  benchmarks/bench.py   M6
  outputs/              (gitignored) demo plots + json
```

## 4. Module specs

Time: 1 tick = 15 min, 96 ticks/day, market open ticks 38–64 (constants in `config.py`).

### M1 `population.py`
- `Population` holds one array per field, length N. Use `add_agents(n)` to append; nodes are never removed.
- **Copula traits:** `age` (Beta(2,3)·67+18), `wealth` (lognormal, median ~50k, σ≈1.3; investable wealth), `impulsiveness` Beta(2,5), `risk_tolerance` Beta(2,2.5), `knowledge` Beta(2,4), `belief_tolerance` (Beta(3,3) scaled to 0.2–1.2), `media_attention` Beta(2,3), `loss_aversion` 1+Gamma(2,0.6). Correlations come from `config.PopulationConfig.correlations`.
- The user's notes list 9 named fields plus `[TBD]`. `belief_tolerance`, `media_attention` and `loss_aversion` are extra fields the model needs. Name them as such in `DECISIONS.md`, and leave the `[TBD]` slot unimplemented.
- **Category** (`non_investor`, `long_term`, `swing`, `day_trader`, plus `media` for outlet nodes): investor probability is logistic on log-wealth, knowledge and risk, with the intercept solved by bisection to hit `investor_share`. Among investors, a softmax: day traders favour young + impulsive + risk-tolerant, long-term favours older + knowledgeable.
- **Platform activity:** per platform, a usage probability (logistic on age, interests and knowledge) and an intensity Beta for users.
- **Activity hours:** a peak hour per agent (mostly evening). `online_prob(hour)` is `base_online · (0.3 + 0.7·gaussian bump around peak)`.
- **Latent attributes (user's three):** offline `community` (sort by age + noise, chunk into lognormal sizes with mean `community_mean_size`), `interests` (8 topics in `config.TOPICS`, Dirichlet mixed with a community preference), `influence` (Pareto α≈1.5).
- **State:** `confidence` ∈ [-1,1] (start N(0,0.1)), `narrative_bias`, `held_narrative` (-1), `perceived_value`, `cash`, `shares`, `entry_price`, `strategy_weights` (N×3). Long-term investors start with an initial position.
- **Media outlets:** `media_per_100k` nodes, category `media`, influence ×50, plus `media_credibility` and `media_bias` arrays.

### M1 `graph.py`
- One `Layer` object per platform with `push(sharer_ids) -> exposure (float32, N)` and `stats()`. Only platform users carry edges.
- **Directed (twitter, instagram):** Chung–Lu. Out-degree is lognormal scaled by activity; targets are weighted by influence. A `homophily` share of edges is sampled inside the source's group (interest cluster for twitter, community for instagram) via one cumulative-sum + `searchsorted` pass. Drop self-loops and duplicates through int64 keys + `np.unique`. Store a **receiver CSR** (row = source, cols = followers), so `push` only touches the sharers' rows: gather with `np.repeat` over indptr ranges, then `np.bincount`. Never do a dense mat-vec over all N per item.
- **Friendship:** lognormal degrees, stubs, `homophily` share inside the community, weighted by degree. Symmetrise, then triadic closure: sample nodes, connect two random neighbours.
- **Reddit:** subs ≈ N / `reddit_agents_per_sub`, each with a topic. Memberships = 1 + Poisson(mean−1), chosen by interest then Zipf sub size. `push`: per-sub score = number of sharers in that sub; per-sub intensity = `reach · score / sqrt(sub_size)`; a member's exposure = sum over their subs (sparse `M @ intensity`).
- **TikTok:** no edges. Exposure = `reach · sqrt(popularity) · cosine(interests, item_topic) · activity`.
- **YouTube:** directed creator→subscriber graph, plus a lag queue handled in diffusion.
- `layer_stats()`: degree percentiles, mean degree, reciprocity (directed), sampled clustering coefficient, and edge overlap between layers (Jaccard).
- `add_nodes(new_ids)`: attach new nodes by preferential attachment within their community/interest group, then rebuild CSR.

### M1 `events.py`
- `Event` dataclass, **exactly the user's fields** (tick, kind, ticker, true_impact, sentiment, credibility, salience, complexity, seeding, parent), plus `id` and `topic` (default `"finance"`).
- `EventQueue` (heapq by tick) and `load_events(json)`.
- `hawkes_events(mu, alpha, beta, n_ticks, rng)`: discrete-time self-exciting arrivals with randomised attributes, for synthetic shocks.
- `seed_agents(event, pop, rng)` for each seeding type: `official` → all media + top-knowledge 0.5% of investors (firms also learn immediately); `outlet` → 3–10 random media nodes; `influencer` → a random agent from the top 0.1% by influence; `insider` → ~5 well-connected investors; `anonymous` → 1 random low-influence agent.
- Broadcast: on an item's first tick, each agent gets extra exposure with probability `salience · media_attention · broadcast_rate`.
- A real event (`true_impact ≠ 0`) moves the hidden fundamental value `V_true *= exp(true_impact)` at injection.

### M2 `items.py`
- Fixed-capacity store (`max_items`). Per-slot arrays: global id, sentiment, credibility, salience, complexity, true_impact, topic, parent, is_narrative, origin (event / mutation / invention / price_news), born tick, total shares. Awareness is a `bool (max_items, N)` matrix; current sharers are index arrays.
- Retire a slot when salience < `retire_salience` and it has no sharers. Before reusing a slot, flush its awareness count into history.
- A lineage log of every item ever created (`id, parent, origin, sentiment, credibility, born, final_aware`), for narrative trees.

### M2 `diffusion.py`
This implements the user's line: *"How far information travels in one cycle is determined by the nature of the event and randomness."*
1. Online mask from the activity hours (investors get `trading_online_boost` during market hours).
2. For each active item: exposure = Σ layers `reach · trust-free push(sharers)`, plus broadcast on the first tick and TikTok algorithmic exposure.
3. `p_see = 1 − exp(−exposure · salience)`, only for agents who are online and not yet aware.
4. **Attention cap:** concatenate the (agent, item, score) candidates that pass the random draw, sort by agent then score, and keep the first `attention_slots` per agent.
5. Mark the kept pairs aware.
6. **Share** (each agent shares an item at most once): `p = base_share · salience · (0.3 + impulsiveness) · (0.6 + 0.8·max(agreement,0) + 0.4·|sentiment|·impulsiveness + 0.5·talking-your-book)`, where agreement = sentiment × confidence, and talking-your-book applies when the item's sign matches the agent's position sign.
7. Decay salience. Run the YouTube lag queue (creators' shares land later).

### M2 `beliefs.py`
These follow the user's lines exactly:
- **Belief:** an item only moves Confidence if `|eff_sentiment − confidence| < belief_tolerance`. Step = `mu0 · (0.5+impulsiveness) · (1 − 0.5·knowledge) · cred_eff · (eff_sentiment − confidence)`, with `cred_eff = credibility^(1+2·knowledge)` and `eff_sentiment = (1−α)·sentiment + α·clip(true_impact · impact_to_sentiment)`, where `α = knowledge · (1 − complexity·(1−knowledge))`. Apply all of a tick's updates simultaneously with `np.add.at`, then clip.
- Agents who become aware of a real event update `perceived_value *= exp(α · true_impact)`.
- **Adopt:** on a belief-moving narrative item, with probability `adopt_rate · (impulsiveness + 1 − knowledge)/2`, set `held_narrative` and move `narrative_bias` toward the item's sentiment.
- **Mutate:** among a narrative/rumour item's sharers, with probability `mutate_rate · impulsiveness · (1 − knowledge)`, the agent mutates it. Create **at most one child per parent per tick**: sentiment pushed further out (×1.4, then clipped), credibility ×0.7, salience ×1.2. Mutators share the child instead.
- **Invent:** checked hourly. If |1-day return| > `invent_threshold`, online agents without an explanation create, with probability `invent_rate · impulsiveness · (1−knowledge) · |ret|/threshold`, **one** invented narrative in the direction of the move (cooldown: one per direction per day). Inventors are its seeds.
- Every tick, Confidence is pulled toward `narrative_bias` for holders and decays toward 0.

### M3 `trading.py`
These follow the user's lines exactly:
- Only investors trade, only when online, only during market hours.
- `expected return = w_f·fundamental + w_c·chartist + w_s·sentiment`, weighted average **by category** (prior from `config.TradingConfig.strategy_prior`). Fundamental = `clip((perceived_value − P)/P, ±0.5)`; chartist = log momentum over the category's `momentum_ticks`; sentiment = `confidence · sentiment_scale`.
- The mix shifts toward whatever has been profitable lately: `w = (1−switching)·prior + switching·softmax(switching_intensity · fitness)`. Fitness per strategy is an EMA of `sign(avg signal_{t−1}) · return_t`.
- `target position = risk_tolerance × wealth × expected return / risk`, where `risk = risk_aversion · iv_daily² · horizon_days`. Clip to [0, 1]·wealth (retail can't short in v1).
- `order = target − current holding`, only if |order value| > `(0.05·(1−impulsiveness) + 0.005)·wealth` (the threshold is lower for impulsive agents).
- **Losses:** if the unrealised loss exceeds `panic_loss`, then with probability `panic_rate·(loss_aversion−1)·impulsiveness` the target becomes 0.
- Limit price = `P · exp(±(0.002 + 0.02·impulsiveness + 0.5·|E|))`, capped at ±10%.

### M3 `firms.py`
- `PropFirms`: capital share from config; target = capital · tanh(k · short momentum + k2 · last tick's order imbalance); tight limits.
- `Funds`: know `V_true` with a 1-day lag; target = capital · clip((V − P)/P · k).
- `DiscretionaryPolicy` protocol: `on_event(event, market_state) -> target_fraction`. The default is rule-based; leave an LLM hook as a docstring only.

### M3 `market.py`
- `MarketState`: price, V_true, per-tick price/volume history, daily OHLC, EWMA realised daily vol, implied vol (constant or a series), momentum helper, a `bs_call(S,K,T,r,σ)` function, and the ATM call price logged each tick.
- `batch_auction(buy_q, buy_lim, sell_q, sell_lim, P, sigma_daily, adv, Y, cap)`:
  - D(p) = Σ buy_q[lim ≥ p] − Σ sell_q[lim ≤ p] (sort + cumulative sums + `searchsorted`).
  - Find the log move r where `D(P·e^r) = sign(r)·adv·(r/(Y·σ))²`, by bisection on r within ±cap.
  - Fill every crossing order at the clearing price; the market maker takes the residual into its inventory.
  - Add noise ~ N(0, noise_frac · σ_daily / √26) on open ticks for unmodelled flow.
  - Return the price, fill masks and volume.
- ADV = `adv_turnover · total shares held`.

### M4 `sim.py`
Order of each tick (from the notes' loop):
1. Inject due events.
2. Diffusion.
3. Beliefs and narratives.
4. If the market is open: firm and agent orders, then the auction, then holdings/cash update.
5. **Next tick feedback**:
   - a move larger than `price_news_threshold` since the last price headline creates a `price_move` Event (seeding `outlet`, sentiment = clip(8·ret), true_impact 0);
   - chartists see momentum on the next tick;
   - invention runs hourly;
   - profitable holders talk up their book (in diffusion);
   - losing holders panic (in trading).

Metrics per tick: price, V_true, volume, mean investor confidence, awareness count for every active item, and awareness of each **event family** (root + descendants) split by platform users and category. `Simulation.run(n_ticks)` returns a results dict. Every run is fully determined by its `seed`.

### M4 `montecarlo.py` / `viz.py` / `run_demo.py`
- MC: build the population and graph once, run R dynamics seeds (optional `multiprocessing` over 2 cores), and return the (R, T) price paths plus quantiles.
- Plots, saved to `outputs/`:
  - a price fan chart with 5/25/50/75/95% bands and V_true;
  - awareness curves for each event family;
  - an awareness distribution by category and by platform;
  - a narrative lineage tree (x = born tick, y = sentiment, lines to parents, marker size = final awareness);
  - stylised facts (return histogram vs normal with kurtosis, ACF of returns vs |returns|).
- `python -m marketsim.run_demo --agents 10000 --days 5 --runs 20` runs a scripted scenario: day 1 an anonymous acquisition rumour (true_impact 0), day 3 a company denial (official, parent = rumour), plus one real earnings miss (true_impact −0.05). It writes plots and `summary.json`.

### M5 `calibration.py`
- `calibrate(observed_log_prices, events, param_space, n_trials, runs_per_trial)`: random search over a few parameters (`impact_Y`, `base_share`, `mu0`, `sentiment_scale`), minimising RMSE between the median simulated and observed log-price paths.
- `recovery_test()`: generate "observed" data from known parameters, calibrate, and report how close the recovered parameters are. **This is the key identifiability check. Write its result into `DECISIONS.md`.**

### M5 `backtest.py`
- CRPS from samples (energy form); a random-walk benchmark (lognormal with trailing realised vol).
- `backtest(price_series, events, origins, horizon)`: for each origin, events at or before the origin only, then MC forward, then CRPS for both models. Report the mean CRPS skill score.
- The demo runs on synthetic series only. Document how to plug in a real CSV (`date, close`) plus an events JSON.

### M5 `event_parser.py`
- `EVENT_JSON_SCHEMA`, `PROMPT_TEMPLATE` (with 3 few-shot examples), `validate_event(dict) -> Event` (clamps ranges, rejects unknown kinds/seedings).
- `parse_headlines(headlines, llm: Callable[[str], str], cache_path)`: temperature 0 is the caller's job; cache by hash.
- `abnormal_return_impact(stock_px, market_px, event_idx, est_window=120, event_window=(0,2))`: market-model CAR. Include the **leakage warning** in its docstring.
- Test it with a fake `llm` callable.

### M6 tests, benchmark, packaging
- **Tests (pytest):**
  - copula sample correlations within ±0.07 of the target (after PSD repair);
  - investor share within ±1pt of the target;
  - graph has no self-loops or duplicates, and the directed layer has heavy-tailed in-degree (max / median > 20 at 10k);
  - auction: monotone D(p), buys − sells = market-maker residual, no fill outside limits, cap respected;
  - higher salience → wider reach (same seed);
  - same seed → identical results;
  - `add_agents` keeps every array the same length and the graph valid;
  - parser rejects bad JSON and clamps ranges.
- **Stylised facts:** report, don't assert, kurtosis of open-tick returns and the |r| autocorrelation at lags 1–10 in the demo summary.
- **`benchmarks/bench.py`:** build time + seconds per tick + peak RSS at 10k, 100k, 1M (1M may need lower degrees given ~7 GB RAM; record what you used). Put the table in the README.
- **README:** what it is, how to run, what's a placeholder, the results of the recovery test and benchmark, known limitations, and the v2 list (dealer gamma hedging, multi-ticker, LLM discretionary funds, fitting graphs to data, the [TBD] trait).

## 5. Milestones and done criteria

| # | Deliverable | Done when |
|---|---|---|
| M1 | population, graph, events + tests | tests pass; `layer_stats()` prints sensible numbers at 10k |
| M2 | items, diffusion, beliefs + tests | a single rumour produces an S-shaped awareness curve; mutations and an invention appear in the lineage |
| M3 | trading, firms, market + tests | auction tests pass; a 5-day 10k run has a non-flat price and positive volume |
| M4 | sim, montecarlo, viz, run_demo | `run_demo` writes all plots + `summary.json` in < 10 min at 10k × 20 runs |
| M5 | calibration, backtest, event_parser + tests | recovery test runs and its result is recorded |
| M6 | benchmark, README, final commit on branch | `pytest` green; benchmark table in README |

Run `pytest -q` before every commit. If a test fails and you can't fix it in reasonable time, mark it `xfail` with a reason and log it in `DECISIONS.md`. Don't delete it.

## 6. What to leave for the user in the morning

1. Branch `feat/marketsim-v1` with one commit per milestone, not merged.
2. `README.md` with run instructions, the benchmark table and the recovery-test result.
3. `DECISIONS.md` listing every judgement call, simplification and xfail.
4. `outputs/` from the demo run (plots + summary.json). Don't commit it; just leave it on disk.
5. A short summary at the end of your session: what works, what's simplified, what's next.
