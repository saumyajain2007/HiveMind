import time

import numpy as np
import pytest
from scipy.stats import spearmanr

from marketsim.config import (
    ALL_PLATFORMS,
    DAY_TRADER,
    LONG_TERM,
    MEDIA,
    NON_INVESTOR,
    SWING,
    TOPICS,
    Config,
    PopulationConfig,
)
from marketsim.population import (
    COPULA_TRAITS,
    FIELD_SPECS,
    Population,
    build_correlation_matrix,
    repair_psd,
    solve_intercept,
)
from marketsim.survey import apply_survey, load_survey

N = 10_000


@pytest.fixture(scope="module")
def pop():
    return Population.build(Config(n_agents=N, seed=0))


def _lengths(p):
    return {name: len(getattr(p, name)) for name in p.field_names}


def test_correlations_match_repaired_target(pop):
    # The copula fixes the correlation of the latent normal scores, not the Pearson correlation of
    # the transformed traits (lognormal wealth attenuates Pearson badly). Rank correlation is
    # invariant to the marginals; 2*sin(pi*rho_s/6) converts it back to the Gaussian correlation.
    people = pop.person_ids
    X = np.column_stack([getattr(pop, t)[people] for t in COPULA_TRAITS])
    est = 2.0 * np.sin(np.pi * spearmanr(X).statistic / 6.0)
    assert np.abs(est - pop.target_corr).max() < 0.07


def test_investor_share_within_one_point(pop):
    cat = pop.category[pop.person_ids]
    share = np.mean(cat != NON_INVESTOR)
    assert abs(share - apply_survey(Config().population).investor_share) < 0.01  # Census + SCF target
    assert set(np.unique(cat)) == {NON_INVESTOR, LONG_TERM, SWING, DAY_TRADER}


def test_solve_intercept_hits_target():
    scores = np.random.default_rng(1).normal(size=5000)
    from scipy.special import expit

    a = solve_intercept(scores, 0.15)
    assert abs(expit(a + scores).mean() - 0.15) < 1e-9


def test_add_agents_keeps_arrays_aligned_and_never_removes(pop):
    p = Population.build(Config(n_agents=2000, seed=3))
    before = {name: getattr(p, name).copy() for name in p.field_names}
    n0 = len(p)
    ids = p.add_agents(300)
    assert len(p) == n0 + 300
    assert np.array_equal(ids, np.arange(n0, n0 + 300))
    assert set(_lengths(p).values()) == {n0 + 300}
    for name, old in before.items():
        assert np.array_equal(getattr(p, name)[:n0], old), name
    assert set(p.community[ids]) <= set(range(len(p.community_pref)))
    p.add_agents(0)
    assert len(p) == n0 + 300
    p.add_media(2)
    assert set(_lengths(p).values()) == {n0 + 302}
    for name, (dtype, shape) in FIELD_SPECS.items():
        assert getattr(p, name).dtype == np.dtype(dtype) and getattr(p, name).shape[1:] == shape


def test_build_time_under_one_second():
    Population.build(Config(n_agents=1000, seed=0))  # warm up imports/caches
    best = min(_timed(lambda s=s: Population.build(Config(n_agents=N, seed=s))) for s in range(3))
    assert best < 1.0


def _timed(fn):
    t = time.perf_counter()
    fn()
    return time.perf_counter() - t


def test_psd_repair():
    traits = ("a", "b", "c")
    R = build_correlation_matrix({("a", "b"): 0.9, ("b", "c"): 0.9, ("a", "c"): -0.9}, traits)
    assert np.linalg.eigvalsh(R).min() < 0
    fixed = repair_psd(R)
    assert np.allclose(fixed, fixed.T)
    assert np.allclose(np.diag(fixed), 1.0)
    assert np.linalg.eigvalsh(fixed).min() > 0
    np.linalg.cholesky(fixed)
    # an already valid matrix is left (almost) alone
    good = build_correlation_matrix(PopulationConfig().correlations)
    assert np.allclose(repair_psd(good), good, atol=1e-5)
    with pytest.raises(ValueError):
        build_correlation_matrix({("a", "zzz"): 0.1}, traits)


def test_same_seed_same_population():
    a = Population.build(Config(n_agents=500, seed=7))
    b = Population.build(Config(n_agents=500, seed=7))
    c = Population.build(Config(n_agents=500, seed=8))
    assert all(np.array_equal(getattr(a, f), getattr(b, f)) for f in a.field_names)
    assert not np.array_equal(a.age, c.age)


def test_trait_ranges_and_marginals(pop):
    p = pop.person_ids
    assert pop.age[p].min() >= 18 and pop.age[p].max() <= 95  # Census adults; 85+ spread over 85-95
    assert pop.belief_tolerance.min() >= 0.2 and pop.belief_tolerance.max() <= 1.2
    assert pop.loss_aversion.min() >= 1.0
    for f in ("impulsiveness", "risk_tolerance", "knowledge", "media_attention"):
        assert getattr(pop, f).min() >= 0.0 and getattr(pop, f).max() <= 1.0
    # wealth follows the SCF 2022 financial-assets distribution (median and 90th percentile)
    q = np.asarray(load_survey("us")["wealth_quantiles"])
    assert abs(np.median(pop.wealth[p]) / q[100] - 1) < 0.08
    assert abs(np.quantile(pop.wealth[p], 0.9) / q[180] - 1) < 0.15


def test_categories_follow_traits(pop):
    p = pop.person_ids
    cat = pop.category[p]
    assert pop.age[p][cat == DAY_TRADER].mean() < pop.age[p][cat == LONG_TERM].mean()
    assert pop.impulsiveness[p][cat == DAY_TRADER].mean() > pop.impulsiveness[p][cat == LONG_TERM].mean()
    assert pop.knowledge[p][cat == LONG_TERM].mean() > pop.knowledge[p][cat == NON_INVESTOR].mean()
    assert pop.wealth[p][cat != NON_INVESTOR].mean() > pop.wealth[p][cat == NON_INVESTOR].mean()


def test_platform_usage(pop):
    p = pop.person_ids
    targets = Config().population.platform_params
    for j, name in enumerate(ALL_PLATFORMS):
        assert abs(pop.platform_use[p, j].mean() - targets[name]["target"]) < 0.02, name
    assert np.all(pop.platform_intensity[~pop.platform_use] == 0)
    assert np.all(pop.platform_intensity[pop.platform_use] > 0)
    tik = ALL_PLATFORMS.index("tiktok")
    assert np.corrcoef(pop.age[p], pop.platform_use[p, tik])[0, 1] < -0.2


def test_activity_hours(pop):
    p = pop.person_ids
    assert pop.peak_hour.min() >= 0 and pop.peak_hour.max() < 24
    evening = np.mean((pop.peak_hour[p] >= 17) & (pop.peak_hour[p] < 24))
    assert evening > 0.5
    base = Config().diffusion.base_online
    peak = pop.peak_hour.copy()
    on_peak = np.array([pop.online_prob(h)[i] for i, h in enumerate(peak[:50])])
    assert np.allclose(on_peak, base)
    far = pop.online_prob((peak[0] + 12) % 24)[0]
    assert base * 0.3 <= far < base * 0.35
    assert pop.online_prob(25.0).shape == (len(pop),)


def test_latent_attributes(pop):
    p = pop.person_ids
    assert np.allclose(pop.interests.sum(axis=1), 1.0) and pop.interests.shape[1] == len(TOPICS)
    sizes = np.bincount(pop.community[p])
    assert abs(sizes.mean() - Config().population.community_mean_size) < 6
    assert sizes.std() / sizes.mean() > 0.3  # heterogeneous (lognormal) sizes
    comm_age = np.bincount(pop.community[p], weights=pop.age[p]) / sizes
    assert comm_age.std() > 5  # communities are age-sorted
    assert pop.influence[p].min() >= 1.0
    infl = np.sort(pop.influence[p])
    alpha_hat = 1.0 / np.mean(np.log(infl[infl >= 2.0] / 2.0))  # Hill estimator at xmin=2
    assert abs(alpha_hat - 1.5) < 0.2
    # community preference shows up in interests
    mean_int = np.array(
        [pop.interests[p][pop.community[p] == c].mean(axis=0) for c in range(len(sizes)) if sizes[c] >= 30]
    )
    assert mean_int.std(axis=0).mean() > 0.01


def test_state_arrays(pop):
    p = Config().market.initial_price
    people = pop.person_ids
    assert abs(pop.confidence[people].mean()) < 0.01 and abs(pop.confidence[people].std() - 0.1) < 0.01
    assert np.all(pop.held_narrative == -1) and np.all(pop.narrative_bias == 0)
    assert np.allclose(pop.strategy_weights.sum(axis=1), 1.0) and pop.strategy_weights.shape == (len(pop), 3)
    lt = pop.category == LONG_TERM
    assert np.all(pop.shares[lt] > 0) and np.all(pop.entry_price[lt] == p)
    assert np.all(pop.shares[~lt] == 0) and np.all(pop.entry_price[~lt] == 0)
    assert np.allclose(pop.cash + pop.shares * p, pop.wealth)
    assert abs(np.median(pop.perceived_value[people]) / p - 1) < 0.01


def test_media_outlets(pop):
    m = pop.media_ids
    cfg = Config().population
    assert len(m) == round(cfg.media_per_100k * N / 100_000)
    assert np.all(pop.category[m] == MEDIA)
    assert np.median(pop.influence[m]) > 10 * np.median(pop.influence[pop.person_ids])
    assert np.all((pop.media_credibility[m] > 0) & (pop.media_credibility[m] < 1))
    assert np.all(np.abs(pop.media_bias[m]) <= 1)
    assert np.all(pop.community[m] == -1)
    # outlets publish on every platform except Friendship (no offline friendships)
    fr = ALL_PLATFORMS.index("friendship")
    others = [j for j in range(len(ALL_PLATFORMS)) if j != fr]
    assert np.all(pop.platform_use[np.ix_(m, others)]) and not pop.platform_use[m, fr].any()
    assert np.all(pop.shares[m] == 0) and np.all(pop.cash[m] == 0)
    assert not np.any(np.isin(pop.investor_ids, m))
