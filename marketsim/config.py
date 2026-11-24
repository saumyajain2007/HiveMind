"""All tunable parameters in one place.

Values marked PLACEHOLDER are reasonable guesses, not fitted to data.
Replace them with values estimated from real data before trusting any output.
"""
from dataclasses import dataclass, field

TICKS_PER_DAY = 96                 # 15-minute ticks
MARKET_OPEN_TICK = 38              # 09:30
MARKET_CLOSE_TICK = 64             # 16:00

TOPICS = ("finance", "tech", "crypto", "energy", "politics", "sports", "entertainment", "health")

CATEGORIES = ("non_investor", "long_term", "swing", "day_trader", "media")
NON_INVESTOR, LONG_TERM, SWING, DAY_TRADER, MEDIA = range(5)

ALL_PLATFORMS = ("twitter", "reddit", "friendship", "instagram", "tiktok", "youtube")


@dataclass
class PopulationConfig:
    # Real-data inputs (marketsim/survey.py): "us" = US Census age + Federal Reserve SCF 2022 wealth,
    # knowledge, stock ownership and trait correlations, from data/population/us.json; "" = the
    # PLACEHOLDER values below everywhere.
    survey: str = "us"
    investor_share: float = 0.15          # PLACEHOLDER (overridden by `survey`): share of agents holding stock
    media_per_100k: float = 50.0          # media outlet nodes per 100k agents
    community_mean_size: float = 60.0     # offline communities (school, work)
    # Trait correlation matrix (Gaussian copula), order = COPULA_TRAITS in population.py
    # PLACEHOLDER: replace with correlations estimated from survey microdata.
    correlations: dict = field(default_factory=lambda: {
        ("age", "wealth"): 0.45, ("age", "impulsiveness"): -0.30, ("age", "risk_tolerance"): -0.25,
        ("age", "knowledge"): 0.20, ("age", "media_attention"): 0.30,
        ("wealth", "knowledge"): 0.30, ("wealth", "risk_tolerance"): 0.10,
        ("impulsiveness", "risk_tolerance"): 0.35, ("impulsiveness", "knowledge"): -0.20,
        ("impulsiveness", "belief_tolerance"): 0.20, ("knowledge", "belief_tolerance"): -0.15,
        ("risk_tolerance", "loss_aversion"): -0.30,
    })
    # Marginals for the copula traits (HANDOFF section 4, M1). All PLACEHOLDER, not fitted to data.
    #   ("beta", a, b, loc, scale) -> loc + scale * Beta(a, b)
    #   ("lognormal", median, sigma) -> exp(log(median) + sigma * Z)
    #   ("gamma", shape, scale, loc) -> loc + Gamma(shape, scale)
    marginals: dict = field(default_factory=lambda: {
        "age": ("beta", 2.0, 3.0, 18.0, 67.0),
        "wealth": ("lognormal", 50_000.0, 1.3),          # investable wealth
        "impulsiveness": ("beta", 2.0, 5.0, 0.0, 1.0),
        "risk_tolerance": ("beta", 2.0, 2.5, 0.0, 1.0),
        "knowledge": ("beta", 2.0, 4.0, 0.0, 1.0),
        "belief_tolerance": ("beta", 3.0, 3.0, 0.2, 1.0),   # 0.2 to 1.2
        "media_attention": ("beta", 2.0, 3.0, 0.0, 1.0),
        "loss_aversion": ("gamma", 2.0, 0.6, 1.0),          # 1 + Gamma(2, 0.6)
    })
    psd_eps: float = 1e-6                 # eigenvalue floor when repairing the correlation matrix
    # Investor logit on the latent (standard-normal) copula scores; intercept solved to hit investor_share
    investor_logit: dict = field(default_factory=lambda: {      # PLACEHOLDER
        "wealth": 1.0, "knowledge": 0.6, "risk_tolerance": 0.4})
    # Category softmax among investors: (intercept, {trait: coef on latent score}); swing is the baseline
    category_logits: dict = field(default_factory=lambda: {     # PLACEHOLDER
        LONG_TERM: (0.0, {"age": 0.8, "knowledge": 0.8, "impulsiveness": -0.3}),
        SWING: (0.4, {}),
        DAY_TRADER: (-1.0, {"age": -0.8, "impulsiveness": 0.8, "risk_tolerance": 0.5}),
    })
    # Platform usage: logistic on latent age/knowledge scores and on interests; intercept solved to hit `target`.
    # interest term = sum_t coef_t * (len(TOPICS) * interests_t - 1)
    platform_params: dict = field(default_factory=lambda: {     # PLACEHOLDER: roughly Pew / Ofcom shaped
        "twitter": {"target": 0.25, "age": -0.3, "knowledge": 0.2,
                    "interests": {"finance": 0.3, "tech": 0.3, "crypto": 0.3, "politics": 0.3}},
        "reddit": {"target": 0.22, "age": -0.5, "knowledge": 0.3,
                   "interests": {"tech": 0.3, "crypto": 0.3, "finance": 0.2, "sports": 0.2}},
        "friendship": {"target": 0.90, "age": -0.1, "knowledge": 0.0, "interests": {}},
        "instagram": {"target": 0.40, "age": -0.8, "knowledge": 0.0,
                      "interests": {"entertainment": 0.3, "sports": 0.2}},
        "tiktok": {"target": 0.35, "age": -0.9, "knowledge": 0.0, "interests": {"entertainment": 0.4}},
        "youtube": {"target": 0.80, "age": -0.3, "knowledge": 0.0, "interests": {}},
    })
    intensity_beta: tuple = (2.0, 3.0)    # PLACEHOLDER: Beta(a, b) usage intensity for platform users
    # Activity hours: mixture of (weight, mean hour, sd hours) for each agent's peak hour (mostly evening)
    peak_hour_mix: tuple = ((0.70, 20.5, 2.0), (0.20, 12.5, 2.5), (0.10, 7.5, 1.5))   # PLACEHOLDER
    online_width: float = 3.0             # PLACEHOLDER: sd (hours) of the gaussian bump around the peak hour
    # Latent attributes
    community_size_sigma: float = 0.8     # PLACEHOLDER: lognormal sigma of community sizes
    community_age_noise: float = 4.0      # PLACEHOLDER: years of noise when sorting agents into communities
    interest_concentration: float = 0.5   # PLACEHOLDER: Dirichlet concentration (individual and community)
    community_interest_mix: float = 0.4   # PLACEHOLDER: weight of the community preference in interests
    influence_alpha: float = 1.5          # Pareto tail exponent
    media_influence_mult: float = 50.0
    media_credibility_beta: tuple = (6.0, 3.0)   # PLACEHOLDER
    media_bias_sd: float = 0.3            # PLACEHOLDER
    # Initial state
    confidence_sd: float = 0.1
    long_term_initial_position: float = 0.5   # PLACEHOLDER: share of wealth long-term investors hold in stock
    perceived_value_noise: float = 0.05   # PLACEHOLDER: sd of log(perceived_value / price), scaled by (1 - knowledge)


@dataclass
class GraphConfig:
    platforms: tuple = ("twitter", "reddit", "friendship", "instagram", "tiktok", "youtube")  # every platform in the design notes
    twitter_mean_out: float = 40.0
    twitter_homophily: float = 0.5        # share of follows inside the agent's main-interest cluster
    instagram_mean_out: float = 60.0
    instagram_homophily: float = 0.6      # share of follows inside the offline community
    friendship_mean_degree: float = 20.0
    friendship_homophily: float = 0.8
    triadic_closure: float = 0.15         # extra edges closing triangles, as a share of edges
    reddit_mean_memberships: float = 3.0
    reddit_agents_per_sub: float = 400.0
    youtube_creator_share: float = 0.01
    youtube_mean_subs: float = 15.0
    youtube_lag_ticks: tuple = (16, 96)   # videos appear 4h to 1 day after a creator decides to cover it
    youtube_homophily: float = 0.5        # PLACEHOLDER: share of subscriptions to creators of the agent's main interest
    degree_sigma: float = 0.8             # PLACEHOLDER: lognormal sigma of out-degree / friend count (before activity scaling)
    reddit_zipf: float = 1.0              # PLACEHOLDER: Zipf exponent of subreddit popularity within a topic
    # exposure per sharer per tick on each layer, and how much people trust what reaches them there
    reach: dict = field(default_factory=lambda: {
        "twitter": 0.08, "instagram": 0.05, "friendship": 0.25, "reddit": 0.6, "tiktok": 0.002, "youtube": 0.15})
    trust: dict = field(default_factory=lambda: {
        "twitter": 0.8, "instagram": 0.7, "friendship": 1.3, "reddit": 0.9, "tiktok": 0.6, "youtube": 1.0})
    # PLACEHOLDER: how strongly items arriving on each platform compete for an agent's attention slots
    attention_boost: dict = field(default_factory=lambda: {
        "twitter": 1.0, "instagram": 1.0, "friendship": 1.2, "reddit": 1.0, "tiktok": 1.1, "youtube": 1.0})


@dataclass
class DiffusionConfig:
    base_online: float = 0.12             # chance an agent checks social media in a 15-min tick at peak hour
    attention_slots: int = 3              # new items an agent can take in per tick
    base_share: float = 0.25
    broadcast_rate: float = 0.15          # TV / push alerts, scaled by salience x media_attention
    salience_decay: float = 0.97          # per tick (half-life ~6h)
    retire_salience: float = 0.03
    share_ttl: int = 32                   # PLACEHOLDER: ticks a share stays in followers' feeds (8h)
    outrage_weight: float = 0.3          # PLACEHOLDER: extra sharing when an item contradicts the agent's view
    exposure_scale: float = 4.0           # PLACEHOLDER: multiplies every layer's reach (salient rumours go viral)
    max_items: int = 128                  # active items kept in memory
    mutate_rate: float = 0.04
    invent_rate: float = 0.002
    invent_threshold: float = 0.03        # |1-day return| that makes agents look for an explanation
    price_news_threshold: float = 0.04    # |move| since last price headline that makes outlets report it


@dataclass
class BeliefConfig:
    mu0: float = 0.35                     # base belief step size
    impact_to_sentiment: float = 10.0     # how knowledgeable agents translate true_impact into sentiment
    adopt_rate: float = 0.5
    narrative_pull: float = 0.02          # per tick pull of Confidence toward held narrative
    confidence_decay: float = 0.002       # per tick forgetting toward 0
    adopt_step: float = 0.5               # PLACEHOLDER: how far narrative_bias moves toward an adopted item's sentiment
    invent_credibility: float = 0.25      # PLACEHOLDER: credibility of an invented explanation
    invent_salience: float = 0.6          # PLACEHOLDER: salience of an invented explanation at birth


@dataclass
class TradingConfig:
    # strategy mix (fundamentalist, chartist, sentiment) per category -- PLACEHOLDER priors
    strategy_prior: dict = field(default_factory=lambda: {
        LONG_TERM: (0.70, 0.10, 0.20), SWING: (0.30, 0.40, 0.30), DAY_TRADER: (0.10, 0.50, 0.40)})
    horizon_days: dict = field(default_factory=lambda: {LONG_TERM: 60.0, SWING: 5.0, DAY_TRADER: 0.5})
    momentum_ticks: dict = field(default_factory=lambda: {LONG_TERM: 960, SWING: 192, DAY_TRADER: 8})
    sentiment_scale: float = 0.05         # full conviction (Confidence = 1) = 5% expected excess return
    switching: float = 0.3                # how far weights move toward recently profitable strategies
    switching_intensity: float = 200.0
    fitness_decay: float = 0.97           # PLACEHOLDER: per-tick EMA decay of each strategy's fitness
    risk_aversion: float = 2.0
    panic_loss: float = 0.10              # unrealised loss that triggers loss-aversion behaviour
    panic_rate: float = 0.05
    trading_online_boost: float = 2.0     # investors check the market more often during trading hours


@dataclass
class MarketConfig:
    initial_price: float = 100.0
    implied_vol: float = 0.30             # annualised; options used as a signal only in v1
    impact_Y: float = 0.7                 # square-root law prefactor
    adv_turnover: float = 0.01            # average daily volume as a share of shares held
    adv_ewma: float = 0.97                # PLACEHOLDER: per-open-tick EWMA weight of the market maker's ADV (tracks traded volume)
    noise_frac: float = 0.3               # unmodelled order flow, as a share of per-tick vol
    mm_news_pass_through: float = 1.0     # PLACEHOLDER: share of a public real event's true_impact the market maker re-quotes at once
    circuit_breaker: float = 0.15         # max |log move| per tick
    option_maturity_days: float = 30.0    # PLACEHOLDER: maturity of the logged ATM call (calendar days)
    risk_free_rate: float = 0.0           # PLACEHOLDER: annualised, continuously compounded
    vol_ewma_lambda: float = 0.94         # PLACEHOLDER: RiskMetrics decay for realised daily vol
    trading_days_per_year: int = 252
    n_prop_firms: int = 5
    n_funds: int = 3
    firm_capital_share: float = 0.15      # firms' capital vs total investor wealth
    prop_momentum_ticks: int = 4          # PLACEHOLDER: prop firms' momentum look-back (1 hour)
    prop_momentum_k: float = 30.0         # PLACEHOLDER: prop target = capital * tanh(k * momentum + k2 * imbalance)
    prop_imbalance_k: float = 0.2         # PLACEHOLDER
    fund_value_k: float = 5.0             # PLACEHOLDER: fund target = capital * clip(k * (V - P) / P, -1, 1)
    fund_lag_ticks: int = 96              # funds know V_true with a 1-day lag
    company_buyback_programme: float = 0.02  # PLACEHOLDER: buyback cash vs total investor wealth (0 = no company agent)
    company_buyback_threshold: float = 0.08  # PLACEHOLDER: discount to its own value at which the company buys back
    company_buyback_daily: float = 0.1       # PLACEHOLDER: share of the programme it may spend per day


@dataclass
class Config:
    n_agents: int = 10_000
    seed: int = 0
    population: PopulationConfig = field(default_factory=PopulationConfig)
    graph: GraphConfig = field(default_factory=GraphConfig)
    diffusion: DiffusionConfig = field(default_factory=DiffusionConfig)
    belief: BeliefConfig = field(default_factory=BeliefConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    market: MarketConfig = field(default_factory=MarketConfig)
