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
    investor_share: float = 0.15          # PLACEHOLDER: share of agents holding a brokerage account
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


@dataclass
class GraphConfig:
    platforms: tuple = ("twitter", "reddit", "friendship")      # v1 set; add "instagram", "tiktok", "youtube"
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


@dataclass
class DiffusionConfig:
    base_online: float = 0.12             # chance an agent checks social media in a 15-min tick at peak hour
    attention_slots: int = 3              # new items an agent can take in per tick
    base_share: float = 0.25
    broadcast_rate: float = 0.15          # TV / push alerts, scaled by salience x media_attention
    salience_decay: float = 0.97          # per tick (half-life ~6h)
    retire_salience: float = 0.03
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
    noise_frac: float = 0.3               # unmodelled order flow, as a share of per-tick vol
    circuit_breaker: float = 0.15         # max |log move| per tick
    n_prop_firms: int = 5
    n_funds: int = 3
    firm_capital_share: float = 0.15      # firms' capital vs total investor wealth


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
