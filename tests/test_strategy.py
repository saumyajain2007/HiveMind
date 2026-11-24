"""Forecast statistics, strategy accounting and the agent-fit moments."""

from __future__ import annotations

import math

import numpy as np
import pytest

from marketsim.agent_fit import MOMENTS, distance, latin_hypercube, moments
from marketsim.backtester import (
    Backtest,
    Costs,
    Signal,
    expected_max_sharpe,
    forecast_fitness,
    probabilistic_sharpe,
)
from marketsim.strategy import COST_BPS, lognormal_stats


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


def test_backtest_accounting() -> None:
    rng = np.random.default_rng(1)
    ret = rng.normal(0.0005, 0.01, 500)
    dates = [f"d{i}" for i in range(500)]
    costs = Costs(commission_bps=1.0, slippage_bps=4.0, borrow_bps_annual=0.0)
    bt = Backtest(dates, ret, benchmark=ret, costs=costs)
    bh = bt.run(Signal("bh", "Buy and hold", "", np.ones(500)))
    # buy and hold pays one entry cost, then compounds the returns
    expected = (1 - COST_BPS / 1e4 + ret[0]) * np.prod(1 + ret[1:])
    assert bh.stats["total_return"] == pytest.approx(expected - 1, rel=1e-9)
    assert bh.stats["beta"] == pytest.approx(1.0, abs=1e-3)
    assert bh.stats["max_drawdown"] <= 0 and bh.stats["n_trades"] == 1
    flat = bt.run(Signal("flat", "Cash", "", np.zeros(500)))
    assert flat.stats["total_return"] == 0 and flat.stats["exposure"] == 0 and not flat.trades
    # a perfect-foresight long/short makes money even after costs, and many trades
    res = bt.run_all([Signal("oracle", "Oracle", "", np.sign(ret)), Signal("bh", "B&H", "", np.ones(500))])
    oracle = res[0].stats
    assert oracle["sharpe"] > 5 and oracle["probabilistic_sharpe"] > 0.99 and oracle["n_trades"] > 100
    assert 0 <= oracle["deflated_sharpe"] <= oracle["probabilistic_sharpe"]
    # shorts pay borrow
    short = Backtest(dates, ret, costs=Costs(0, 0, 100.0)).run(Signal("s", "Short", "", -np.ones(500)))
    assert short.stats["costs"] == pytest.approx(500 * 100 / 1e4 / 252)


def test_deflation_grows_with_trials() -> None:
    assert expected_max_sharpe(1, 0.01) == 0
    assert expected_max_sharpe(100, 0.01) > expected_max_sharpe(10, 0.01) > 0
    # the same track record is less convincing when it is the best of many tries
    assert probabilistic_sharpe(0.05, 750, 0.0, 3.0) > probabilistic_sharpe(0.05, 750, 0.0, 3.0, sr_star=0.04)


def test_forecast_fitness() -> None:
    rng = np.random.default_rng(4)
    signal = rng.normal(0, 1, 2000)
    actual = 0.3 * signal + rng.normal(0, 1, 2000)
    from scipy.stats import norm

    f = forecast_fitness(0.3 * signal, norm.cdf(0.3 * signal), actual)
    assert 0.2 < f["information_coefficient"] < 0.4 and f["ic_t"] > 5
    assert f["hit_rate"] > 0.55 and f["brier"] < f["brier_climatology"]
    noise = forecast_fitness(rng.normal(0, 1, 2000), np.full(2000, 0.5), actual)
    assert abs(noise["information_coefficient"]) < 0.06


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
