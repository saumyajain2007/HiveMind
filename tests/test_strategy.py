"""Forecast statistics, strategy accounting and the agent-fit moments."""

from __future__ import annotations

import math

import numpy as np
import pytest

from marketsim.agent_fit import MOMENTS, distance, latin_hypercube, moments
from marketsim.strategy import COST_BPS, lognormal_stats, strategy_stats


def test_lognormal_stats_match_samples() -> None:
    rng = np.random.default_rng(0)
    p0, mu, s = 100.0, 0.001, 0.02
    st = lognormal_stats(p0, mu, s)
    x = p0 * np.exp(rng.normal(mu, s, 400_000))
    assert st["mean"] == pytest.approx(x.mean(), rel=1e-3)
    assert st["sd"] == pytest.approx(x.std(), rel=1e-2)
    assert st["q50"] == pytest.approx(p0 * math.exp(mu))
    assert st["q05"] < st["q25"] < st["q50"] < st["q75"] < st["q95"]
    assert st["p_up"] == pytest.approx((x > p0).mean(), abs=3e-3)


def test_strategy_accounting() -> None:
    rng = np.random.default_rng(1)
    ret = rng.normal(0.0005, 0.01, 500)
    bh = strategy_stats(np.ones(500), ret, ret, rng)
    # buy and hold pays one entry cost, then compounds the returns
    expected = (1 - COST_BPS / 1e4 + ret[0]) * np.prod(1 + ret[1:])
    assert bh["total_return"] == pytest.approx(expected - 1, rel=1e-9)
    assert bh["beta"] == pytest.approx(1.0, abs=1e-3)
    assert bh["max_drawdown"] <= 0
    flat = strategy_stats(np.zeros(500), ret, ret, rng)
    assert flat["total_return"] == 0 and flat["exposure"] == 0
    # a perfect-foresight long/short makes money even after costs
    oracle = strategy_stats(np.sign(ret), ret, ret, rng)
    assert oracle["sharpe"] > 5 and oracle["p_sharpe_not_above_buy_hold"] < 0.01


def test_moments_and_distance() -> None:
    rng = np.random.default_rng(2)
    wins = []
    for _ in range(4):
        r = rng.standard_t(4, 62) * 0.015
        v = 1e6 * (1 + 30 * np.abs(r)) * rng.uniform(0.9, 1.1, 62)
        mask = np.zeros(62, bool)
        mask[30] = True
        r[30] = 0.06
        wins.append((r, v, mask))
    m = moments(wins)
    assert set(m) == set(MOMENTS)
    assert m["volume_corr"] > 0.5 and m["earnings_ratio"] > 2 and m["kurtosis"] > 0
    assert distance(m, m) == 0
    worse = {**m, "sd": m["sd"] * 2}
    assert distance(worse, m) > 1
    pts = latin_hypercube(10, np.random.default_rng(0))
    assert len(pts) == 10 and all(len(p) == len(pts[0]) for p in pts)
