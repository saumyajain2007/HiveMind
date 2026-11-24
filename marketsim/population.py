"""Agent population (M1).

``Population`` stores one NumPy array per field, each with first dimension N.
Agents are appended with ``add_agents`` and never removed.

Generative model
----------------
1. Eight continuous traits come from a Gaussian copula: multivariate normal with
   correlation R (built from ``PopulationConfig.correlations``, repaired to PSD by
   eigenvalue clipping, then rescaled to unit diagonal), mapped to uniforms with the
   normal CDF, then through each trait's inverse CDF (``PopulationConfig.marginals``).
2. Categories are sampled *conditionally* on the latent copula scores: an investor
   logit (intercept solved by bisection to hit ``investor_share``) followed by a
   softmax over day trader / swing / long-term among investors.
3. Latent attributes: offline ``community``, ``interests``, ``influence``.
4. Platform usage (logistic on age, interests, knowledge; intercepts solved to hit
   each platform's target share) and a Beta usage intensity.
5. Activity hours: a peak hour per agent and ``online_prob(hour)``.
6. State arrays and media-outlet nodes.

``[TBD]`` from the design notes is deliberately not implemented.
"""

from __future__ import annotations

import numpy as np
from scipy.special import betaincinv, expit, gammaincinv, ndtr

from .config import (
    ALL_PLATFORMS,
    CATEGORIES,
    DAY_TRADER,
    LONG_TERM,
    MEDIA,
    NON_INVESTOR,
    SWING,
    TOPICS,
    Config,
)

# Order of the copula (rows/columns of R). belief_tolerance, media_attention and loss_aversion
# are extra fields the model needs (see DECISIONS.md).
COPULA_TRAITS = (
    "age",
    "wealth",
    "impulsiveness",
    "risk_tolerance",
    "knowledge",
    "belief_tolerance",
    "media_attention",
    "loss_aversion",
)

_P = len(ALL_PLATFORMS)
_T = len(TOPICS)

# name -> (dtype, trailing shape). Every field is an array of shape (N, *trailing).
FIELD_SPECS: dict[str, tuple] = {
    "category": (np.int8, ()),
    **{name: (np.float64, ()) for name in COPULA_TRAITS},
    "peak_hour": (np.float64, ()),
    "platform_use": (np.bool_, (_P,)),  # columns follow config.ALL_PLATFORMS
    "platform_intensity": (np.float64, (_P,)),  # 0 for non-users
    "community": (np.int32, ()),  # -1 for media outlets
    "interests": (np.float64, (_T,)),  # rows sum to 1; columns follow config.TOPICS
    "influence": (np.float64, ()),
    "confidence": (np.float64, ()),
    "narrative_bias": (np.float64, ()),
    "held_narrative": (np.int32, ()),  # -1 = none
    "perceived_value": (np.float64, ()),
    "cash": (np.float64, ()),
    "shares": (np.float64, ()),
    "entry_price": (np.float64, ()),  # 0 = no position
    "strategy_weights": (np.float64, (3,)),  # fundamentalist, chartist, sentiment
    "media_credibility": (np.float64, ()),  # 0 for non-media
    "media_bias": (np.float64, ()),  # 0 for non-media
    "connections": (
        np.float64,
        (),
    ),  # ties in the social graph (followers + friends); set once the graph exists
}


# ---------------------------------------------------------------------------
# Correlation matrix helpers
# ---------------------------------------------------------------------------
def build_correlation_matrix(correlations: dict, traits=COPULA_TRAITS) -> np.ndarray:
    """Symmetric matrix with unit diagonal from ``{(trait_a, trait_b): rho}``."""
    index = {t: i for i, t in enumerate(traits)}
    R = np.eye(len(traits))
    for (a, b), rho in correlations.items():
        if a not in index or b not in index:
            raise ValueError(f"unknown trait in correlations: {(a, b)}")
        if a == b:
            raise ValueError(f"diagonal entry given for {a}")
        R[index[a], index[b]] = R[index[b], index[a]] = rho
    return R


def repair_psd(R: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    """Nearest-PSD repair by eigenvalue clipping, then rescale to unit diagonal."""
    R = 0.5 * (R + R.T)
    w, V = np.linalg.eigh(R)
    w = np.clip(w, eps, None)
    R = (V * w) @ V.T
    R = 0.5 * (R + R.T)
    d = np.sqrt(np.diag(R))
    R = R / np.outer(d, d)
    np.fill_diagonal(R, 1.0)
    return R


def solve_intercept(scores: np.ndarray, target: float, iters: int = 80) -> float:
    """Bisection for ``a`` such that ``mean(expit(a + scores)) == target``."""
    if not 0.0 < target < 1.0:
        raise ValueError("target share must be in (0, 1)")
    lo, hi = -40.0 - float(np.max(scores)), 40.0 - float(np.min(scores))
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if expit(mid + scores).mean() < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _marginal_ppf(spec: tuple, z: np.ndarray) -> np.ndarray:
    kind = spec[0]
    if kind == "lognormal":
        _, median, sigma = spec
        return np.exp(np.log(median) + sigma * z)
    u = np.clip(ndtr(z), 1e-12, 1.0 - 1e-12)
    if kind == "beta":
        _, a, b, loc, scale = spec
        return loc + scale * betaincinv(a, b, u)
    if kind == "gamma":
        _, shape, scale, loc = spec
        return loc + scale * gammaincinv(shape, u)
    raise ValueError(f"unknown marginal kind: {kind}")


def _dirichlet(rng, alpha: float, n: int, k: int) -> np.ndarray:
    g = rng.gamma(alpha, size=(n, k)) + 1e-12
    return g / g.sum(axis=1, keepdims=True)


# ---------------------------------------------------------------------------
# Population
# ---------------------------------------------------------------------------
class Population:
    """Struct-of-arrays agent store. Build with ``Population.build(cfg)``.

    Fields (all length N, see ``FIELD_SPECS``): category, the eight copula traits,
    peak_hour, platform_use, platform_intensity, community, interests, influence,
    confidence, narrative_bias, held_narrative, perceived_value, cash, shares,
    entry_price, strategy_weights, media_credibility, media_bias.
    """

    # One array per field (FIELD_SPECS), created in __init__; declared here for type checkers.
    category: np.ndarray
    age: np.ndarray
    wealth: np.ndarray
    impulsiveness: np.ndarray
    risk_tolerance: np.ndarray
    knowledge: np.ndarray
    belief_tolerance: np.ndarray
    media_attention: np.ndarray
    loss_aversion: np.ndarray
    peak_hour: np.ndarray
    platform_use: np.ndarray
    platform_intensity: np.ndarray
    community: np.ndarray
    interests: np.ndarray
    influence: np.ndarray
    confidence: np.ndarray
    narrative_bias: np.ndarray
    held_narrative: np.ndarray
    perceived_value: np.ndarray
    cash: np.ndarray
    shares: np.ndarray
    entry_price: np.ndarray
    strategy_weights: np.ndarray
    media_credibility: np.ndarray
    media_bias: np.ndarray
    connections: np.ndarray

    def __init__(self, config: Config | None = None, rng: np.random.Generator | None = None):
        self.cfg = config if config is not None else Config()
        self.rng = rng if rng is not None else np.random.default_rng(self.cfg.seed)
        pc = self.cfg.population
        self.target_corr = repair_psd(build_correlation_matrix(pc.correlations), pc.psd_eps)
        self._chol = np.linalg.cholesky(self.target_corr)
        for name, (dtype, shape) in FIELD_SPECS.items():
            setattr(self, name, np.empty((0, *shape), dtype=dtype))
        self.community_pref: np.ndarray | None = None  # (n_communities, T) lookup table
        self._investor_intercept: float | None = None  # calibrated on the first batch
        self._platform_intercepts: np.ndarray | None = None
        pri = np.full((len(CATEGORIES), 3), 1.0 / 3.0)
        for cat, w in self.cfg.trading.strategy_prior.items():
            pri[cat] = w
        self._strategy_table = pri

    # -- construction -------------------------------------------------------
    @classmethod
    def build(
        cls, config: Config | None = None, n_agents: int | None = None, seed: int | None = None
    ) -> Population:
        """``n_agents`` people plus ``media_per_100k`` outlet nodes (at least one)."""
        cfg = config if config is not None else Config()
        n = cfg.n_agents if n_agents is None else n_agents
        rng = np.random.default_rng(cfg.seed if seed is None else seed)
        pop = cls(cfg, rng)
        pop.add_agents(n)
        n_media = round(cfg.population.media_per_100k * n / 100_000.0)
        if cfg.population.media_per_100k > 0 and n > 0:
            n_media = max(1, n_media)
        if n_media:
            pop.add_media(n_media)
        return pop

    # -- basic views --------------------------------------------------------
    def __len__(self) -> int:
        return int(self.category.shape[0])

    @property
    def n(self) -> int:
        return len(self)

    @property
    def field_names(self) -> tuple:
        return tuple(FIELD_SPECS)

    @property
    def media_ids(self) -> np.ndarray:
        return np.flatnonzero(self.category == MEDIA)

    @property
    def person_ids(self) -> np.ndarray:
        return np.flatnonzero(self.category != MEDIA)

    @property
    def investor_ids(self) -> np.ndarray:
        return np.flatnonzero((self.category != NON_INVESTOR) & (self.category != MEDIA))

    def online_prob(self, hour: float, base_online: float | None = None) -> np.ndarray:
        """Chance each agent is online at ``hour`` (0-24):
        ``base_online * (0.3 + 0.7 * gaussian bump around the agent's peak hour)``.

        ``base_online`` defaults to this population's config; diffusion passes its own."""
        d = np.abs(float(hour) % 24.0 - self.peak_hour)
        d = np.minimum(d, 24.0 - d)
        bump = np.exp(-0.5 * (d / self.cfg.population.online_width) ** 2)
        base = self.cfg.diffusion.base_online if base_online is None else base_online
        return base * (0.3 + 0.7 * bump)

    # -- appending ----------------------------------------------------------
    def add_agents(self, n: int) -> np.ndarray:
        """Append ``n`` ordinary agents sampled from the generative model. Never removes.
        Returns the new agents' ids."""
        if n < 0:
            raise ValueError("n must be >= 0")
        if n == 0:
            return np.arange(len(self), len(self))
        return self._append(self._sample_people(n))

    def add_media(self, n: int) -> np.ndarray:
        """Append ``n`` media-outlet nodes (category ``media``). Returns their ids."""
        if n < 0:
            raise ValueError("n must be >= 0")
        if n == 0:
            return np.arange(len(self), len(self))
        return self._append(self._sample_media(n))

    def _append(self, batch: dict) -> np.ndarray:
        m = len(batch["category"])
        start = len(self)
        for name, (dtype, shape) in FIELD_SPECS.items():
            arr = np.asarray(batch[name], dtype=dtype)
            if arr.shape != (m, *shape):
                raise ValueError(f"field {name}: expected {(m, *shape)}, got {arr.shape}")
            setattr(self, name, np.concatenate([getattr(self, name), arr], axis=0))
        return np.arange(start, start + m)

    # -- sampling -----------------------------------------------------------
    def _draw_copula(self, n: int):
        """Latent scores z (n, 8) and the trait arrays, as a dict."""
        pc = self.cfg.population
        z = self.rng.standard_normal((n, len(COPULA_TRAITS))) @ self._chol.T
        traits = {name: _marginal_ppf(pc.marginals[name], z[:, j]) for j, name in enumerate(COPULA_TRAITS)}
        return {name: z[:, j] for j, name in enumerate(COPULA_TRAITS)}, traits

    def _peak_hours(self, n: int) -> np.ndarray:
        mix = np.asarray(self.cfg.population.peak_hour_mix, dtype=float)
        comp = self.rng.choice(len(mix), size=n, p=mix[:, 0] / mix[:, 0].sum())
        return (mix[comp, 1] + mix[comp, 2] * self.rng.standard_normal(n)) % 24.0

    def _state(self, n, category, wealth, knowledge, long_term_position=True) -> dict:
        """Initial state arrays shared by people and media."""
        pc, p0 = self.cfg.population, self.cfg.market.initial_price
        shares = np.zeros(n)
        entry = np.zeros(n)
        if long_term_position:
            lt = category == LONG_TERM
            shares[lt] = pc.long_term_initial_position * wealth[lt] / p0
            entry[lt] = p0
        return {
            "confidence": np.clip(self.rng.normal(0.0, pc.confidence_sd, n), -1.0, 1.0),
            "narrative_bias": np.zeros(n),
            "held_narrative": np.full(n, -1, dtype=np.int32),
            "perceived_value": p0
            * np.exp(self.rng.standard_normal(n) * pc.perceived_value_noise * (1.0 - knowledge)),
            "cash": wealth - shares * p0,
            "shares": shares,
            "entry_price": entry,
            "strategy_weights": self._strategy_table[category],
        }

    def _assign_community(self, age: np.ndarray) -> np.ndarray:
        pc = self.cfg.population
        n = len(age)
        if self.community_pref is None:
            # First batch: sort by age + noise, chunk into lognormal sizes with the configured mean.
            s = pc.community_size_sigma
            mu = np.log(pc.community_mean_size) - 0.5 * s * s
            k = int(1.5 * n / pc.community_mean_size) + 10
            sizes = np.maximum(1, np.rint(self.rng.lognormal(mu, s, k))).astype(np.int64)
            csum = np.cumsum(sizes)
            while csum[-1] < n:
                more = np.maximum(1, np.rint(self.rng.lognormal(mu, s, k))).astype(np.int64)
                sizes = np.concatenate([sizes, more])
                csum = np.cumsum(sizes)
            last = int(np.searchsorted(csum, n))
            sizes = sizes[: last + 1].copy()
            sizes[last] -= csum[last] - n
            ids = np.repeat(np.arange(len(sizes), dtype=np.int32), sizes)
            order = np.argsort(age + self.rng.normal(0.0, pc.community_age_noise, n))
            community = np.empty(n, dtype=np.int32)
            community[order] = ids
            self.community_pref = _dirichlet(self.rng, pc.interest_concentration, len(sizes), _T)
            return community
        # Later batches join existing communities: pick an existing person of similar age
        # (size-proportional, age-affine) and take their community.
        people = self.person_ids
        order = np.argsort(self.age[people])
        sorted_age = self.age[people][order]
        target = age + self.rng.normal(0.0, pc.community_age_noise, n)
        idx = np.clip(np.searchsorted(sorted_age, target), 0, len(sorted_age) - 1)
        return self.community[people[order[idx]]]

    def _sample_people(self, n: int) -> dict:
        pc, rng = self.cfg.population, self.rng
        zs, traits = self._draw_copula(n)

        # Investor / non-investor: logistic on latent log-wealth, knowledge and risk.
        score = sum(coef * zs[name] for name, coef in pc.investor_logit.items())
        if self._investor_intercept is None:
            self._investor_intercept = solve_intercept(score, pc.investor_share)
        is_inv = rng.random(n) < expit(self._investor_intercept + score)
        category = np.full(n, NON_INVESTOR, dtype=np.int8)
        inv = np.flatnonzero(is_inv)
        if len(inv):
            cats = (LONG_TERM, SWING, DAY_TRADER)
            logits = np.empty((len(inv), 3))
            for j, cat in enumerate(cats):
                b0, coefs = pc.category_logits[cat]
                logits[:, j] = b0 + sum(c * zs[name][inv] for name, c in coefs.items())
            logits -= logits.max(axis=1, keepdims=True)
            p = np.exp(logits)
            cum = np.cumsum(p / p.sum(axis=1, keepdims=True), axis=1)
            pick = (rng.random((len(inv), 1)) > cum).sum(axis=1).clip(0, 2)
            category[inv] = np.asarray(cats, dtype=np.int8)[pick]

        # Latent attributes.
        community = self._assign_community(traits["age"])
        assert self.community_pref is not None  # set by _assign_community on the first batch
        w = pc.community_interest_mix
        interests = (1.0 - w) * _dirichlet(rng, pc.interest_concentration, n, _T) + w * self.community_pref[
            community
        ]
        influence = 1.0 + rng.pareto(pc.influence_alpha, n)

        # Platform usage and intensity.
        logit = np.empty((n, _P))
        for j, plat in enumerate(ALL_PLATFORMS):
            par = pc.platform_params[plat]
            wt = np.zeros(_T)
            for topic, c in par["interests"].items():
                wt[TOPICS.index(topic)] = c
            logit[:, j] = (
                par["age"] * zs["age"] + par["knowledge"] * zs["knowledge"] + _T * (interests @ wt) - wt.sum()
            )
        if self._platform_intercepts is None:
            self._platform_intercepts = np.array(
                [
                    solve_intercept(logit[:, j], pc.platform_params[p]["target"])
                    for j, p in enumerate(ALL_PLATFORMS)
                ]
            )
        use = rng.random((n, _P)) < expit(logit + self._platform_intercepts)
        a, b = pc.intensity_beta
        intensity = rng.beta(a, b, (n, _P)) * use

        batch = {
            "category": category,
            **traits,
            "peak_hour": self._peak_hours(n),
            "platform_use": use,
            "platform_intensity": intensity,
            "community": community,
            "interests": interests,
            "influence": influence,
            "media_credibility": np.zeros(n),
            "media_bias": np.zeros(n),
            "connections": np.zeros(n),
        }
        batch.update(self._state(n, category, traits["wealth"], traits["knowledge"]))
        return batch

    def _sample_media(self, n: int) -> dict:
        pc, rng = self.cfg.population, self.rng
        _, traits = self._draw_copula(n)
        category = np.full(n, MEDIA, dtype=np.int8)
        use = np.ones((n, _P), dtype=bool)
        use[:, ALL_PLATFORMS.index("friendship")] = False  # outlets have no offline friends
        traits["wealth"] = np.zeros(n)  # outlets hold no money and never trade
        cred_a, cred_b = pc.media_credibility_beta
        batch = {
            "category": category,
            **traits,
            "peak_hour": self._peak_hours(n),
            "platform_use": use,  # outlets publish on every platform except Friendship
            "platform_intensity": use.astype(np.float64),
            "community": np.full(n, -1, dtype=np.int32),
            "interests": _dirichlet(rng, pc.interest_concentration, n, _T),
            "influence": pc.media_influence_mult * (1.0 + rng.pareto(pc.influence_alpha, n)),
            "media_credibility": rng.beta(cred_a, cred_b, n),
            "media_bias": np.clip(rng.normal(0.0, pc.media_bias_sd, n), -1.0, 1.0),
            "connections": np.zeros(n),
        }
        batch.update(
            self._state(n, category, traits["wealth"], traits["knowledge"], long_term_position=False)
        )
        batch["confidence"] = np.zeros(n)
        return batch
