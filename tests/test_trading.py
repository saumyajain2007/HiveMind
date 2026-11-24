"""Tests for marketsim.trading and marketsim.firms (issue #9)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from marketsim.config import DAY_TRADER, LONG_TERM, SWING, TICKS_PER_DAY, Config
from marketsim.events import Event
from marketsim.firms import Funds, PropFirms, build_firms
from marketsim.market import MarketState, is_market_open
from marketsim.population import Population
from marketsim.trading import LIMIT_CAP, OrderBatch, Trading, filled_mask

CFG = Config(n_agents=10_000, seed=0)


@pytest.fixture()
def world() -> tuple[Population, Trading, MarketState]:
    pop = Population.build(CFG)
    return pop, Trading(pop, CFG, np.random.default_rng(0)), MarketState(CFG.market)


def test_weights_start_at_priors_and_shift_to_the_winner(world) -> None:
    pop, tr, _m = world
    tr.update_fitness(0.0)
    inv = pop.investor_ids
    lt = inv[pop.category[inv] == LONG_TERM][0]
    w0 = pop.strategy_weights[lt].copy()
    tc = CFG.trading
    assert w0 == pytest.approx((1 - tc.switching) * np.array(tc.strategy_prior[LONG_TERM]) + tc.switching / 3)
    tr._last_signal = np.array([-0.01, 0.02, 0.0])  # chartists were long, fundamentalists short
    for _ in range(30):
        tr.update_fitness(0.01)  # ... and the price went up
    assert tr.fitness[1] > 0 > tr.fitness[0]
    assert pop.strategy_weights[lt, 1] > w0[1] and pop.strategy_weights[lt, 0] < w0[0]
    assert pop.strategy_weights[inv].sum(axis=1) == pytest.approx(np.ones(len(inv)))


def test_target_sizing_formula(world) -> None:
    pop, tr, m = world
    ids = pop.investor_ids[:50]
    E = np.full(50, 0.002)
    t = tr.target_value(ids, E, m)
    eq = pop.cash[ids] + pop.shares[ids] * m.price
    risk = CFG.trading.risk_aversion * m.iv_daily() ** 2 * tr.horizon[pop.category[ids]]
    assert t == pytest.approx(np.clip(pop.risk_tolerance[ids] * eq * E / risk, 0, eq))
    assert (tr.target_value(ids, -E, m) == 0).all()  # no shorting
    assert tr.target_value(ids, np.full(50, 10.0), m) == pytest.approx(eq)  # at most all equity


def test_threshold_is_lower_for_impulsive_agents(world) -> None:
    pop, tr, m = world
    a, b = pop.investor_ids[:2]
    pop.cash[[a, b]], pop.shares[[a, b]] = 10_000.0, 0.0
    pop.impulsiveness[a], pop.impulsiveness[b] = 0.9, 0.1
    th = tr.threshold(np.array([a, b]), m.price)
    assert th[0] < th[1]
    assert th[0] == pytest.approx((0.05 * 0.1 + 0.005) * 10_000)


def test_panic_needs_a_loss_and_loss_aversion(world) -> None:
    pop, tr, _m = world
    ids = pop.investor_ids[:200]
    pop.shares[ids], pop.entry_price[ids] = 10.0, 100.0
    pop.loss_aversion[ids], pop.impulsiveness[ids] = 1.0 + 1.0 / CFG.trading.panic_rate, 1.0  # p = 1
    assert tr.panics(ids, 95.0).sum() == 0  # 5% loss < panic_loss
    assert tr.panics(ids, 85.0).all()
    pop.loss_aversion[ids] = 1.0
    assert tr.panics(ids, 85.0).sum() == 0  # no loss aversion, no panic


def test_orders_respect_limits_cash_and_holdings(world) -> None:
    pop, tr, m = world
    tr.update_fitness(0.0)
    rng = np.random.default_rng(1)
    pop.confidence[:] = rng.uniform(-1, 1, pop.n)
    o = tr.orders(m, np.ones(pop.n, bool))
    assert len(o) > 0 and (o.qty > 0).any() and (o.qty < 0).any()
    assert np.all(np.abs(np.log(o.limit / m.price)) <= LIMIT_CAP + 1e-12)
    assert np.all((o.limit > m.price) == (o.qty > 0))
    assert np.all(o.qty[o.qty > 0] * o.limit[o.qty > 0] <= pop.cash[o.owner[o.qty > 0]] + 1e-6)
    assert np.all(-o.qty[o.qty < 0] <= pop.shares[o.owner[o.qty < 0]] + 1e-9)
    assert np.isin(o.owner, pop.investor_ids).all()
    assert len(tr.orders(m, np.zeros(pop.n, bool))) == 0  # nobody online, no orders


def test_settle_updates_cash_shares_and_entry(world) -> None:
    pop, tr, _m = world
    a, b = pop.investor_ids[:2]
    pop.cash[[a, b]], pop.shares[[a, b]], pop.entry_price[[a, b]] = 1000.0, 10.0, 90.0
    batch = OrderBatch(np.array([a, b]), np.array([5.0, -10.0]), np.array([101.0, 99.0]))
    tr.settle(batch, 100.0)
    assert pop.shares[a] == 15.0 and pop.cash[a] == 500.0
    assert pop.entry_price[a] == pytest.approx((10 * 90 + 5 * 100) / 15)
    assert pop.shares[b] == 0.0 and pop.cash[b] == 2000.0 and pop.entry_price[b] == 0.0
    batch = OrderBatch(np.array([a]), np.array([1.0]), np.array([99.0]))
    tr.settle(batch, 100.0)  # limit below price: not filled
    assert pop.shares[a] == 15.0


def test_prop_firms_follow_momentum_and_imbalance() -> None:
    m = MarketState(CFG.market)
    for p in (100.0, 100.5, 101.0, 101.5, 102.0):
        m.prices.append(p)
    m.price = 102.0
    props = PropFirms(2, 1e6, momentum_ticks=4, k=100.0, k2=1.0)
    props.observe(OrderBatch(np.arange(2), np.array([5.0, -1.0]), np.array([1.0, 1.0])))
    assert props.imbalance == pytest.approx(4 / 6)
    frac = props.target_fraction(m)
    assert frac == pytest.approx(np.full(2, math.tanh(100 * math.log(102 / 100) + 4 / 6)))
    o = props.orders(m)
    assert (o.qty > 0).all() and np.allclose(o.limit, 102.0 * math.exp(0.003))
    props.settle(o, 102.1)
    assert props.shares.sum() == pytest.approx(o.qty.sum())


def test_funds_use_lagged_value_but_read_official_news_at_once() -> None:
    m = MarketState(CFG.market)
    for t in range(200):
        m.record_tick(t)
    funds = Funds(1, 1e6, k=5.0, lag_ticks=96)
    assert funds.known_value(m) == pytest.approx(100.0)
    rumour = Event(200, "leak", 0, -0.1, -0.5, 0.5, 0.5, 0.5, "insider")
    m.apply_fundamental_shock(rumour.true_impact)
    funds.on_event(rumour, m, 200)  # not official: funds only see it a day later
    m.record_tick(200)
    assert funds.known_value(m) == pytest.approx(100.0)
    for t in range(201, 297):
        m.record_tick(t)
    assert funds.known_value(m) == pytest.approx(100 * math.exp(-0.1))
    earnings = Event(297, "earnings", 0, -0.05, -0.7, 0.95, 0.8, 0.5, "official")
    m.apply_fundamental_shock(earnings.true_impact)
    funds.on_event(earnings, m, 297)
    m.record_tick(297)
    assert funds.known_value(m) == pytest.approx(100 * math.exp(-0.15))
    assert funds.target_fraction(m)[0] == pytest.approx(5 * (100 * math.exp(-0.15) - 100) / 100)


def test_discretionary_policy_overrides_for_the_day() -> None:
    class Bullish:
        def on_event(self, event: Event, market: MarketState) -> float | None:
            return 0.8

    m = MarketState(CFG.market)
    m.record_tick(40)
    funds = Funds(2, 1e6, k=5.0, lag_ticks=96, policy=Bullish())
    funds.on_event(Event(40, "statement", 0, 0.0, 0.5, 0.9, 0.5, 0.2, "official"), m, 40)
    assert funds.target_fraction(m) == pytest.approx([0.8, 0.8])
    m.record_tick(96)
    assert funds.target_fraction(m) == pytest.approx([0.0, 0.0])  # next day: rule again


def test_five_day_run_moves_the_price_with_volume() -> None:
    """Trading + firms + auction on a population with dispersed beliefs (no diffusion)."""
    pop = Population.build(CFG)
    rng = np.random.default_rng(7)
    tr = Trading(pop, CFG, rng)
    m = MarketState(CFG.market)
    props, funds = build_firms(CFG.market, float(pop.wealth[pop.investor_ids].sum()))
    pop.confidence[:] = np.clip(rng.normal(0, 0.3, pop.n), -1, 1)
    funds_shock = Event(2 * TICKS_PER_DAY + 40, "earnings", 0, -0.05, -0.7, 0.95, 0.8, 0.5, "official")
    tr.update_fitness(0.0)
    volume = 0.0
    for t in range(5 * TICKS_PER_DAY):
        if t == funds_shock.tick:
            m.apply_fundamental_shock(funds_shock.true_impact)
            funds.on_event(funds_shock, m, t)
        if not is_market_open(t):
            m.record_tick(t)
            continue
        pop.confidence[:] = np.clip(0.9 * pop.confidence + rng.normal(0, 0.1, pop.n), -1, 1)
        online = rng.random(pop.n) < 0.3
        retail = tr.orders(m, online)
        firm_p, firm_f = props.orders(m), funds.orders(m)
        q = np.concatenate([retail.qty, firm_p.qty, firm_f.qty])
        lim = np.concatenate([retail.limit, firm_p.limit, firm_f.limit])
        held = float(pop.shares.sum() + np.maximum(props.shares, 0).sum() + np.maximum(funds.shares, 0).sum())
        prev = m.price
        res = m.clear(q[q > 0], lim[q > 0], -q[q < 0], lim[q < 0], held, rng)
        tr.settle(retail, res.price)
        props.settle(firm_p, res.price)
        funds.settle(firm_f, res.price)
        props.observe(retail)
        m.record_tick(t, res)
        tr.update_fitness(math.log(res.price / prev))
        tr.remember_signals(m)
        volume += res.volume
    prices = np.array(m.prices)
    assert volume > 0 and np.std(np.diff(np.log(prices))) > 0
    assert prices.max() / prices.min() > 1.01
    assert len(m.ohlc) == 5
    assert (pop.shares >= 0).all() and np.isfinite(pop.cash).all()
    assert {SWING, DAY_TRADER} <= set(pop.category[np.flatnonzero(pop.entry_price > 0)].tolist())


def test_filled_mask() -> None:
    b = OrderBatch(np.arange(4), np.array([1.0, 1.0, -1.0, -1.0]), np.array([101.0, 99.0, 99.0, 101.0]))
    assert filled_mask(b, 100.0).tolist() == [True, False, True, False]
