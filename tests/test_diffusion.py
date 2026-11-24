"""Tests for marketsim.diffusion (issue #6)."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from marketsim.config import ALL_PLATFORMS, MARKET_OPEN_TICK, Config
from marketsim.diffusion import Diffusion
from marketsim.events import Event, seed_agents
from marketsim.graph import SocialGraph, YouTubeLayer
from marketsim.items import ItemStore
from marketsim.population import Population

CFG = Config(n_agents=10_000, seed=0)
RUMOUR_TICK = 96 + 40  # day 2, 10:00


@pytest.fixture(scope="module")
def world() -> tuple[Population, SocialGraph]:
    pop = Population.build(CFG)
    return pop, SocialGraph.build(pop, CFG.graph, np.random.default_rng(1))


def make(
    pop: Population, graph: SocialGraph, cfg: Config = CFG, seed: int = 0
) -> tuple[ItemStore, Diffusion]:
    dc = cfg.diffusion
    items = ItemStore(pop.n, dc.max_items, dc.retire_salience, dc.share_ttl)
    return items, Diffusion(pop, graph, items, cfg, np.random.default_rng(seed))


def rumour(salience: float = 0.7, seeding: str = "anonymous", tick: int = RUMOUR_TICK) -> Event:
    return Event(tick, "rumour", 0, 0.0, 0.8, 0.2, salience, 0.2, seeding, id=0)


def run_rumour(
    world: tuple[Population, SocialGraph], ev: Event, seed: int, ticks: int = 2 * 96, cfg: Config = CFG
) -> list[int]:
    pop, graph = world
    items, d = make(pop, graph, cfg, seed)
    curve = []
    for t in range(ev.tick, ev.tick + ticks):
        if t == ev.tick:
            items.from_event(ev, t, seeds=seed_agents(ev, pop, d.rng))
        d.step(t)
        curve.append(items.family_aware_count(0))
    return curve


def test_single_rumour_gives_an_s_curve(world: tuple[Population, SocialGraph]) -> None:
    curves = [run_rumour(world, rumour(0.7), seed) for seed in range(8)]
    viral = [c for c in curves if c[-1] > 0.05 * world[0].n]
    assert viral, "a salient rumour should go viral in some runs"
    c = np.array(viral[0])
    hourly = np.diff(c[::4])
    peak = int(np.argmax(hourly))
    assert 1 <= peak < len(hourly) - 4  # growth speeds up, then slows down
    assert hourly[0] < hourly[peak] / 2 and hourly[-1] < hourly[peak] / 10
    assert np.all(np.diff(c) >= 0)  # awareness never falls


def test_higher_salience_reaches_further(world: tuple[Population, SocialGraph]) -> None:
    seeds = range(8)
    high = [run_rumour(world, rumour(0.9), s)[-1] for s in seeds]
    low = [run_rumour(world, rumour(0.3), s)[-1] for s in seeds]
    assert np.mean(high) > 3 * np.mean(low)


def test_same_seed_same_spread(world: tuple[Population, SocialGraph]) -> None:
    assert run_rumour(world, rumour(), 3, ticks=96) == run_rumour(world, rumour(), 3, ticks=96)


def test_attention_cap_and_share_once(world: tuple[Population, SocialGraph]) -> None:
    pop, graph = world
    cfg = replace(
        CFG, diffusion=replace(CFG.diffusion, attention_slots=2, base_online=1.0, exposure_scale=50.0)
    )
    items, d = make(pop, graph, cfg, seed=4)
    hub = np.argsort(-pop.influence)[:30]
    for _ in range(8):
        items.create(
            sentiment=0.9,
            credibility=0.5,
            salience=1.0,
            complexity=0.1,
            born=RUMOUR_TICK,
            origin="event",
            seeds=hub,
        )
    r = d.step(RUMOUR_TICK)
    assert len(r.seen_agents) > 0
    assert np.bincount(r.seen_agents).max() <= 2  # at most 2 new items per agent per tick
    assert r.candidates >= len(r.seen_agents)
    # sharing: each agent shares an item at most once, and only items it knows
    assert not (items.shared & ~items.aware).any()
    total = sum(rec.total_shares for rec in items.lineage)
    assert total == int(items.shared.sum())


def test_offline_agents_see_nothing_but_broadcast(world: tuple[Population, SocialGraph]) -> None:
    pop, graph = world
    cfg = replace(CFG, diffusion=replace(CFG.diffusion, base_online=0.0))
    items, d = make(pop, graph, cfg)
    official = Event(RUMOUR_TICK, "earnings", 0, -0.05, -0.7, 0.95, 0.8, 0.5, "official", id=0)
    slot = items.from_event(official, RUMOUR_TICK, seeds=seed_agents(official, pop, d.rng))
    n_seeds = int(items.aware[slot].sum())
    r = d.step(RUMOUR_TICK)
    assert len(r.seen_agents) > 50  # TV / push alerts reach people who are not online
    r2 = d.step(RUMOUR_TICK + 1)
    assert len(r2.seen_agents) == 0  # nobody online, no broadcast after the first tick
    assert items.aware[slot].sum() == n_seeds + len(r.seen_agents)


def test_anonymous_rumours_are_not_broadcast(world: tuple[Population, SocialGraph]) -> None:
    pop, graph = world
    cfg = replace(CFG, diffusion=replace(CFG.diffusion, base_online=0.0))
    items, d = make(pop, graph, cfg)
    ev = rumour(1.0)
    items.from_event(ev, ev.tick, seeds=seed_agents(ev, pop, d.rng))
    assert len(d.step(ev.tick).seen_agents) == 0


def test_investors_are_online_more_during_market_hours(world: tuple[Population, SocialGraph]) -> None:
    pop, graph = world
    _, d = make(pop, graph)
    inv = pop.investor_ids
    non = np.flatnonzero(pop.category == 0)
    open_t, closed_t = MARKET_OPEN_TICK + 4, MARKET_OPEN_TICK - 6
    o = np.mean(
        [d.online_mask(open_t)[inv].mean() / max(d.online_mask(open_t)[non].mean(), 1e-9) for _ in range(20)]
    )
    c = np.mean(
        [
            d.online_mask(closed_t)[inv].mean() / max(d.online_mask(closed_t)[non].mean(), 1e-9)
            for _ in range(20)
        ]
    )
    assert o > 1.5 * c


def test_items_fade_and_retire_with_lineage(world: tuple[Population, SocialGraph]) -> None:
    pop, graph = world
    items, d = make(pop, graph, seed=2)
    ev = rumour(0.5)
    items.from_event(ev, ev.tick, seeds=seed_agents(ev, pop, d.rng))
    retired_at = None
    for t in range(ev.tick, ev.tick + 3 * 96):
        r = d.step(t)
        if r.retired:
            retired_at = t
            break
    assert retired_at is not None and not items.active.any()
    rec = items.lineage[0]
    assert rec.retired == retired_at and rec.final_aware == items.family_aware_count(0)


def test_youtube_uploads_arrive_after_the_production_lag() -> None:
    cfg = replace(CFG, n_agents=3_000, graph=replace(CFG.graph, platforms=("youtube",)))
    pop = Population.build(cfg)
    graph = SocialGraph.build(pop, cfg.graph, np.random.default_rng(0), platforms=["youtube"])
    yt = graph.layers["youtube"]
    assert isinstance(yt, YouTubeLayer)
    creator = int(yt.creators[np.argmax(yt.in_degree()[yt.creators])])
    items, d = make(pop, graph, cfg, seed=1)
    slot = items.create(
        sentiment=0.8,
        credibility=0.4,
        salience=0.9,
        complexity=0.2,
        born=0,
        origin="event",
        seeds=np.array([creator]),
    )
    subscribers = yt.indices[yt.indptr[creator] : yt.indptr[creator + 1]]
    first_seen = None
    for t in range(0, 140):
        r = d.step(t)
        if np.isin(r.seen_agents[r.seen_slots == slot], subscribers).any() and first_seen is None:
            first_seen = t
    lo, hi = cfg.graph.youtube_lag_ticks
    assert first_seen is not None and lo <= first_seen <= hi + cfg.diffusion.share_ttl
    assert items.lineage[0].retired == -1 or items.lineage[0].retired >= first_seen


def test_new_agents_join_mid_run(world: tuple[Population, SocialGraph]) -> None:
    cfg = replace(CFG, n_agents=2_000)
    pop = Population.build(cfg)
    graph = SocialGraph.build(pop, cfg.graph, np.random.default_rng(0))
    items, d = make(pop, graph, cfg)
    ev = rumour(0.8)
    items.from_event(ev, ev.tick, seeds=seed_agents(ev, pop, d.rng))
    d.step(ev.tick)
    new = pop.add_agents(300)
    graph.add_nodes(pop, new, np.random.default_rng(1))
    d.step(ev.tick + 1)
    assert items.aware.shape[1] == pop.n


def test_all_platforms_run(world: tuple[Population, SocialGraph]) -> None:
    pop, _ = world
    graph = SocialGraph.build(pop, CFG.graph, np.random.default_rng(1), platforms=ALL_PLATFORMS)
    items, d = make(pop, graph)
    ev = rumour(0.8, seeding="influencer")
    items.from_event(ev, ev.tick, seeds=seed_agents(ev, pop, d.rng))
    for t in range(ev.tick, ev.tick + 48):
        d.step(t)
    assert items.family_aware_count(0) > 1
