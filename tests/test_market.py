"""Tests for marketsim.market (issue #8)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from marketsim.config import MARKET_CLOSE_TICK, MARKET_OPEN_TICK, TICKS_PER_DAY, MarketConfig
from marketsim.market import (
    MarketState,
    batch_auction,
    bs_call,
    demand_curve,
    is_market_open,
    mm_supply,
)

P0, SIGMA, ADV, Y, CAP = 100.0, 0.02, 10_000.0, 0.7, 0.15


def random_book(rng: np.random.Generator, n: int = 400, skew: float = 0.0):
    """Random limit orders around P0. `skew` > 0 adds buy pressure."""
    nb, ns = n // 2, n // 2
    buy_q = rng.lognormal(3, 1, nb) * (1 + skew)
    sell_q = rng.lognormal(3, 1, ns)
    buy_lim = P0 * np.exp(rng.normal(0, 0.02, nb))
    sell_lim = P0 * np.exp(rng.normal(0, 0.02, ns))
    return buy_q, buy_lim, sell_q, sell_lim


# --------------------------------------------------------------------------- Black–Scholes


def test_bs_call_reference_values() -> None:
    # Hull, Options, Futures and Other Derivatives: standard textbook examples.
    assert bs_call(100, 100, 1.0, 0.05, 0.2) == pytest.approx(10.450583572185565, abs=1e-8)
    assert bs_call(42, 40, 0.5, 0.10, 0.2) == pytest.approx(4.759422392871532, abs=1e-8)


def test_bs_call_matches_independent_erf_formula() -> None:
    def ref(S: float, K: float, T: float, r: float, s: float) -> float:
        N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))  # noqa: E731
        d1 = (math.log(S / K) + (r + s * s / 2) * T) / (s * math.sqrt(T))
        return S * N(d1) - K * math.exp(-r * T) * N(d1 - s * math.sqrt(T))

    rng = np.random.default_rng(0)
    for _ in range(200):
        S, K = rng.uniform(20, 200, 2)
        T, r, s = rng.uniform(0.01, 3), rng.uniform(-0.01, 0.08), rng.uniform(0.05, 1.0)
        assert bs_call(S, K, T, r, s) == pytest.approx(ref(S, K, T, r, s), abs=1e-8)


def test_bs_call_limits_and_parity() -> None:
    assert bs_call(110, 100, 0.0, 0.05, 0.3) == 10.0
    assert bs_call(90, 100, 0.0, 0.05, 0.3) == 0.0
    assert bs_call(110, 100, 1.0, 0.0, 0.0) == pytest.approx(10.0)
    # put-call parity via a put priced with the symmetric formula: C − P = S − K e^{−rT}
    S, K, T, r, s = 100.0, 95.0, 0.5, 0.03, 0.25
    put = bs_call(K * math.exp(-r * T), S, T, 0.0, s)  # put on S = call on K e^{-rT} struck at S (r=0)
    assert bs_call(S, K, T, r, s) - put == pytest.approx(S - K * math.exp(-r * T), abs=1e-9)


# --------------------------------------------------------------------------- demand curve


def test_demand_curve_monotone_and_exact() -> None:
    rng = np.random.default_rng(1)
    bq, bl, sq, sl = random_book(rng)
    D = demand_curve(bq, bl, sq, sl)
    grid = np.linspace(80, 120, 2001)
    d = D(grid)
    assert np.all(np.diff(d) <= 1e-9)  # non-increasing
    for p in [85.0, 99.3, float(bl[7]), float(sl[3]), 117.0]:  # includes exact limit prices
        expected = bq[bl >= p].sum() - sq[sl <= p].sum()
        assert float(D(p)) == pytest.approx(expected)


def test_mm_supply_square_root_law() -> None:
    # Market maker supplies Q at move r  <=>  r = Y σ sqrt(Q / ADV)
    for Q in [1.0, 100.0, 5_000.0]:
        r = Y * SIGMA * math.sqrt(Q / ADV)
        assert float(mm_supply(r, ADV, Y, SIGMA)) == pytest.approx(Q)
        assert float(mm_supply(-r, ADV, Y, SIGMA)) == pytest.approx(-Q)


# --------------------------------------------------------------------------- auction


@pytest.mark.parametrize("seed", range(20))
def test_auction_invariants(seed: int) -> None:
    rng = np.random.default_rng(seed)
    bq, bl, sq, sl = random_book(rng, skew=rng.uniform(-0.5, 3))
    res = batch_auction(bq, bl, sq, sl, P0, SIGMA, ADV, Y, CAP, noise_sd=0.002, rng=rng)

    # no fill outside a limit, and every crossing order is filled
    assert np.all(bl[res.buy_fill] >= res.price) and np.all(bl[~res.buy_fill] < res.price)
    assert np.all(sl[res.sell_fill] <= res.price) and np.all(sl[~res.sell_fill] > res.price)
    # buys − sells = what the market maker absorbed
    assert res.bought - res.sold == pytest.approx(-res.mm_delta)
    assert res.bought == pytest.approx(bq[res.buy_fill].sum())
    assert res.sold == pytest.approx(sq[res.sell_fill].sum())
    assert res.volume == max(res.bought, res.sold)
    # cap respected, price consistent with the log return
    assert abs(res.log_return) <= CAP + 1e-12
    assert res.price == pytest.approx(P0 * math.exp(res.log_return))


def test_auction_solves_impact_equation() -> None:
    """Without noise, the clearing move sits where demand crosses the market maker's curve."""
    rng = np.random.default_rng(3)
    bq, bl, sq, sl = random_book(rng, n=2000, skew=1.0)
    res = batch_auction(bq, bl, sq, sl, P0, SIGMA, ADV, Y, CAP)
    D = demand_curve(bq, bl, sq, sl)
    r = res.impact_return
    eps = 1e-9
    f = lambda x: float(D(P0 * math.exp(x)) - mm_supply(x, ADV, Y, SIGMA))  # noqa: E731
    assert f(r - eps) >= 0 >= f(r + eps)
    assert res.log_return > 0  # buy pressure lifts the price


def test_auction_direction_follows_imbalance() -> None:
    lim_buy, lim_sell = np.array([P0 * 1.05]), np.array([P0 * 0.95])
    up = batch_auction(np.array([5_000.0]), lim_buy, np.zeros(0), np.zeros(0), P0, SIGMA, ADV, Y, CAP)
    down = batch_auction(np.zeros(0), np.zeros(0), np.array([5_000.0]), lim_sell, P0, SIGMA, ADV, Y, CAP)
    assert up.log_return > 0 > down.log_return
    assert up.log_return == pytest.approx(-down.log_return)
    # a single aggressive order of size Q moves the price by Y σ sqrt(Q/ADV)
    assert up.log_return == pytest.approx(Y * SIGMA * math.sqrt(5_000 / ADV), rel=1e-6)
    assert up.mm_delta == pytest.approx(-5_000.0)


def test_auction_cap_binds_and_limits_hold() -> None:
    huge = np.array([1e12])
    res = batch_auction(huge, np.array([1e9]), np.zeros(0), np.zeros(0), P0, SIGMA, ADV, Y, CAP)
    assert res.capped and res.log_return == pytest.approx(CAP)
    # buyer whose limit is below the capped price is not filled
    res2 = batch_auction(
        np.array([1e12, 10.0]), np.array([1e9, P0 * 1.01]), np.zeros(0), np.zeros(0), P0, SIGMA, ADV, Y, CAP
    )
    assert res2.buy_fill.tolist() == [True, False]


def test_auction_empty_book_no_move() -> None:
    e = np.zeros(0)
    res = batch_auction(e, e, e, e, P0, SIGMA, ADV, Y, CAP)
    assert res.log_return == pytest.approx(0.0, abs=1e-12) and res.volume == 0.0
    res0 = batch_auction(e, e, e, e, P0, SIGMA, 0.0, Y, CAP)  # no market-maker depth
    assert res0.log_return == pytest.approx(0.0, abs=1e-12)


def test_auction_noise_needs_rng_and_is_reproducible() -> None:
    e = np.zeros(0)
    with pytest.raises(ValueError):
        batch_auction(e, e, e, e, P0, SIGMA, ADV, Y, CAP, noise_sd=0.01)
    a = batch_auction(e, e, e, e, P0, SIGMA, ADV, Y, CAP, noise_sd=0.01, rng=np.random.default_rng(9))
    b = batch_auction(e, e, e, e, P0, SIGMA, ADV, Y, CAP, noise_sd=0.01, rng=np.random.default_rng(9))
    assert a.price == b.price != P0


def test_auction_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        batch_auction(np.array([-1.0]), np.array([P0]), np.zeros(0), np.zeros(0), P0, SIGMA, ADV, Y, CAP)


# --------------------------------------------------------------------------- market state


def test_market_hours() -> None:
    assert not is_market_open(MARKET_OPEN_TICK - 1)
    assert is_market_open(MARKET_OPEN_TICK) and is_market_open(MARKET_CLOSE_TICK - 1)
    assert not is_market_open(MARKET_CLOSE_TICK)
    assert is_market_open(TICKS_PER_DAY + MARKET_OPEN_TICK)


def _run_days(state: MarketState, days: int, rng: np.random.Generator) -> None:
    for tick in range(days * TICKS_PER_DAY):
        if is_market_open(tick):
            bq, bl, sq, sl = random_book(rng, n=100)
            state.record_tick(tick, state.clear(bq * 0.1, bl, sq * 0.1, sl, total_shares_held=1e6, rng=rng))
        else:
            state.record_tick(tick)


def test_market_state_history_and_ohlc() -> None:
    state = MarketState(MarketConfig())
    _run_days(state, 3, np.random.default_rng(4))
    T = 3 * TICKS_PER_DAY
    assert len(state.prices) == len(state.volumes) == len(state.atm_call) == len(state.v_true_hist) == T
    assert len(state.ohlc) == 3
    prices = np.asarray(state.prices)
    for d, (o, h, l, c) in enumerate(state.ohlc):
        day = prices[d * TICKS_PER_DAY + MARKET_OPEN_TICK : d * TICKS_PER_DAY + MARKET_CLOSE_TICK]
        assert (o, h, l, c) == (day[0], day.max(), day.min(), day[-1])
    closed = [t for t in range(T) if not is_market_open(t)]
    assert all(state.volumes[t] == 0.0 for t in closed)
    assert prices.std() > 0  # price moves


def test_market_state_vol_and_option_signal() -> None:
    cfg = MarketConfig(implied_vol=0.3)
    state = MarketState(cfg)
    assert state.daily_vol == pytest.approx(0.3 / math.sqrt(252))
    assert state.iv_daily() == pytest.approx(0.3 / math.sqrt(252))
    expected = bs_call(100, 100, cfg.option_maturity_days / 365, cfg.risk_free_rate, 0.3)
    assert state.atm_call_price() == pytest.approx(expected)
    _run_days(state, 2, np.random.default_rng(5))
    assert state.daily_vol > 0 and state.daily_vol != pytest.approx(0.3 / math.sqrt(252))


def test_implied_vol_series() -> None:
    series = np.linspace(0.2, 0.6, 10)
    state = MarketState(MarketConfig(), implied_vol=series)
    assert state.iv_annual(0) == pytest.approx(0.2)
    assert state.iv_annual(9) == pytest.approx(0.6)
    assert state.iv_annual(50) == pytest.approx(0.6)  # held at the last value


def test_momentum_and_fundamental_shock() -> None:
    state = MarketState(MarketConfig())
    assert state.momentum(5) == 0.0
    for t, p in enumerate([100.0, 101.0, 103.0, 102.0]):
        state.price = p
        state.record_tick(t)
    assert state.momentum(1) == pytest.approx(math.log(102 / 103))
    assert state.momentum(3) == pytest.approx(math.log(102 / 100))
    assert state.momentum(100) == pytest.approx(math.log(102 / 100))  # clamps to oldest
    mom = state.momentum(np.array([1, 3]))
    assert isinstance(mom, np.ndarray) and mom.shape == (2,)
    state.apply_fundamental_shock(-0.05)
    assert state.v_true == pytest.approx(100 * math.exp(-0.05))


def test_mm_inventory_tracks_imbalance() -> None:
    state = MarketState(MarketConfig())
    res = state.clear(
        np.array([500.0]),
        np.array([120.0]),
        np.zeros(0),
        np.zeros(0),
        total_shares_held=1e6,
        rng=np.random.default_rng(0),
    )
    state.record_tick(MARKET_OPEN_TICK, res)
    assert state.mm_inventory == pytest.approx(-500.0)
