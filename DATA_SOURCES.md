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

| Parameter | What to estimate | Candidate source |
|---|---|---|
| Platform use by age | Usage probability per platform | Pew Research Center social media fact sheets; Ofcom Adults' Media Use |
| Twitter / Instagram degrees, reciprocity, clustering | Directed-graph statistics | SNAP (`twitter`, `ego-Twitter`, `higgs-twitter`) |
| Friendship degree, clustering | Undirected-graph statistics | SNAP (`ego-Facebook`, `facebook-combined`) |
| Reddit memberships, sub sizes | Membership counts and distribution | Arctic Shift Reddit dumps (Pushshift access is restricted) |
| YouTube creator share, subscriptions | Creator→subscriber structure | Published YouTube network studies |

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
