# Data sources

Where each `PLACEHOLDER` in `marketsim/config.py` should eventually come from. Nothing here is fetched at runtime; fitting is offline work.

## Population (`PopulationConfig`)

| Parameter | What to estimate | Candidate source |
|---|---|---|
| `investor_share` | Share of adults with a brokerage account | Fed SCF; FINRA Investor Education Foundation surveys |
| `correlations` | Correlations between age, wealth, risk tolerance, knowledge, impulsiveness | Survey microdata (SCF, FINRA NFCS, UK FCA Financial Lives) |
| Trait marginals | Age, wealth and literacy distributions | Census / ONS; SCF wealth percentiles |
| `community_mean_size` | Offline community sizes | Sociology literature on workplace / school group sizes |

## Platforms and graphs (`GraphConfig`)

New in #3: `degree_sigma` (spread of degrees; fit to the degree percentiles), `reddit_zipf` (sub-size tail; fit to the sub-size distribution), `youtube_homophily` (topic concentration of subscriptions).


| Parameter | What to estimate | Candidate source |
|---|---|---|
| Platform use by age | Usage probability per platform | Pew Research Center social media fact sheets; Ofcom Adults' Media Use |
| Twitter / Instagram degrees, reciprocity, clustering | Directed-graph statistics | SNAP (`twitter`, `ego-Twitter`, `higgs-twitter`) |
| Friendship degree, clustering | Undirected-graph statistics | SNAP (`ego-Facebook`, `facebook-combined`) |
| Reddit memberships, sub sizes | Membership counts and distribution | Arctic Shift Reddit dumps (Pushshift access is restricted) |
| YouTube creator share, subscriptions | Creator→subscriber structure | Published YouTube network studies |

### Target statistics for `graph.layer_stats()`

Published values to fit the generators against. The numbers are for the whole platform or a sample and must be rescaled to the simulated population size.

| Layer | Statistic | Published value | Source |
|---|---|---|---|
| Twitter | Reciprocity | ≈ 22% of follow links reciprocated (2009 crawl) | Kwak, Lee, Park, Moon, *What is Twitter, a social network or a news media?*, WWW 2010 |
| Twitter | Follower distribution | Heavy-tailed (power-law-like up to ~10⁵ followers) | Kwak et al. 2010 |
| Twitter | Clustering | 0.565 average (ego networks, biased upward) | SNAP `twitter_combined` (81,306 nodes, 1.77M edges) |
| Friendship | Clustering, mean degree | 0.606 average clustering, mean degree ≈ 43.7 (ego networks) | SNAP `ego-Facebook` (4,039 nodes, 88,234 edges) |
| Friendship | Degree distribution | Median ≈ 99 friends; clustering falls with degree | Ugander, Karrer, Backstrom, Marlow, *The Anatomy of the Facebook Social Graph*, 2011 |
| Reddit | Subreddits per active user, subreddit sizes | TBD | Arctic Shift dumps: count distinct subreddits each author posts or comments in |
| Instagram | Degrees, reciprocity | TBD (no public SNAP graph) | Literature search needed |
| YouTube | Subscriptions per user, subscribers per creator | TBD | SNAP `com-Youtube` gives groups, not subscriptions; literature search needed |
| All | Cross-platform overlap | TBD | Pew platform-overlap tables (share of users of X who also use Y) |

## Diffusion and beliefs (`DiffusionConfig`, `BeliefConfig`)

| Parameter | What to estimate | Candidate source |
|---|---|---|
| `base_share`, `salience_decay` | Share and decay rates | Cascade studies on SNAP `higgs-twitter`; Reddit comment timing |
| `mu0`, `adopt_rate`, `mutate_rate` | Belief dynamics | Calibrated in #12 (not directly observable) |

## Market (`MarketConfig`, `TradingConfig`)

| Parameter | What to estimate | Candidate source |
|---|---|---|
| `impact_Y` | Square-root impact prefactor | Market-impact literature (Y ≈ 0.5–1) |
| `adv_turnover` | Daily turnover | Exchange volume data for the target ticker |
| `implied_vol` | ATM implied volatility | Options data (CBOE) for the target ticker |
| Strategy priors | Investor style mix | Calibrated in #12 |
