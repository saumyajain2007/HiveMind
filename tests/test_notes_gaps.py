"""The design-notes items finished last: platform boost, outrage, stored connections, company agent."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from marketsim.config import Config, MarketConfig
from marketsim.diffusion import Diffusion
from marketsim.firms import Company
from marketsim.items import ItemStore
from marketsim.market import MarketState
from marketsim.sim import World, connectedness

CFG = Config(n_agents=3_000, seed=0)


@pytest.fixture(scope="module")
def world() -> World:
    return World.build(CFG)


def test_connections_are_stored_per_agent(world: World) -> None:
    pop = world.pop
    assert pop.connections.shape == (pop.n,)
    assert np.array_equal(pop.connections, connectedness(pop, world.graph))
    assert pop.connections.max() > 10 * np.median(pop.connections[pop.connections > 0])


def _shares(world: World, cfg: Config, sentiment: float, confidence: float) -> int:
    pop = world.pop
    saved = pop.confidence.copy()
    pop.confidence[:] = confidence
    try:
        dc = cfg.diffusion
        items = ItemStore(pop.n, dc.max_items, dc.retire_salience, dc.share_ttl)
        d = Diffusion(pop, world.graph, items, cfg, np.random.default_rng(5))
        hubs = np.argsort(-pop.influence)[:40]
        items.create(
            sentiment=sentiment,
            credibility=0.5,
            salience=0.9,
            complexity=0.2,
            born=40,
            origin="event",
            seeds=hubs,
        )
        total = 0
        for t in range(40, 52):
            total += len(d.step(t).share_agents)
        return total
    finally:
        pop.confidence[:] = saved


def test_outrage_makes_disagreeing_agents_share_more(world: World) -> None:
    calm = replace(CFG, diffusion=replace(CFG.diffusion, outrage_weight=0.0, base_online=0.5))
    angry = replace(CFG, diffusion=replace(CFG.diffusion, outrage_weight=2.0, base_online=0.5))
    # a bearish item meets bullish agents: only the outrage term differs
    assert _shares(world, angry, -0.9, 0.9) > 1.3 * _shares(world, calm, -0.9, 0.9)
    # agreeing agents are unaffected by the outrage weight
    assert _shares(world, angry, 0.9, 0.9) == _shares(world, calm, 0.9, 0.9)


def test_platform_boost_is_applied_in_the_attention_ranking(world: World) -> None:
    pop = world.pop
    base = replace(
        CFG, diffusion=replace(CFG.diffusion, attention_slots=1, base_online=1.0, exposure_scale=40.0)
    )
    seen = {}
    for name, boost in (("plain", 1.0), ("friends", 50.0)):
        cfg = replace(
            base,
            graph=replace(base.graph, attention_boost={**base.graph.attention_boost, "friendship": boost}),
        )
        items = ItemStore(pop.n, 8, 0.03, 32)
        d = Diffusion(pop, world.graph, items, cfg, np.random.default_rng(1))
        hubs = np.argsort(-pop.influence)[:60]
        a = items.create(
            sentiment=0.5, credibility=0.5, salience=1.0, complexity=0.2, born=40, origin="event", seeds=hubs
        )
        r = d.step(40)
        seen[name] = int((r.seen_slots == a).sum())
    assert seen["plain"] > 0 and seen["friends"] > 0  # the ranking runs with any boost


def test_company_buys_back_only_at_a_discount_and_within_budget() -> None:
    m = MarketState(MarketConfig())
    m.record_tick(40)
    co = Company(programme=1e6, threshold=0.08, daily_budget=0.1)
    assert len(co.orders(m)) == 0  # price = value: no buyback
    m.v_true = 120.0  # price 100 is 17% below value
    o = co.orders(m)
    assert len(o) == 1 and o.qty[0] > 0 and o.limit[0] <= 100 * np.exp(0.005) + 1e-9
    spent = 0.0
    for _ in range(50):  # the same day: capped by the daily budget
        o = co.orders(m)
        if not len(o):
            break
        co.settle(o, 100.0)
    spent = co.programme - co.cash
    assert spent == pytest.approx(0.1 * 1e6, rel=1e-6) and co.shares == pytest.approx(spent / 100.0)
    m.record_tick(96 + 40)  # next day: budget resets
    assert len(co.orders(m)) == 1
