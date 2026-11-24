"""Tests for marketsim.beliefs (issue #7)."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from marketsim.beliefs import Beliefs
from marketsim.config import MEDIA, Config
from marketsim.diffusion import Diffusion
from marketsim.events import Event, seed_agents
from marketsim.graph import SocialGraph
from marketsim.items import ItemStore
from marketsim.population import Population

CFG = Config(n_agents=2_000, seed=0)


def setup(cfg: Config = CFG, seed: int = 0) -> tuple[Population, ItemStore, Beliefs]:
    pop = Population.build(cfg)
    items = ItemStore(pop.n, cfg.diffusion.max_items, cfg.diffusion.retire_salience, cfg.diffusion.share_ttl)
    return pop, items, Beliefs(pop, items, cfg, np.random.default_rng(seed))


def item(items: ItemStore, sentiment: float = 0.8, **kw: object) -> int:
    args: dict = dict(credibility=0.8, salience=0.6, complexity=0.0, born=0, origin="event")
    args.update(kw)
    return items.create(sentiment=sentiment, **args)


def person(pop: Population) -> int:
    return int(np.flatnonzero(pop.category != MEDIA)[0])


def test_outside_tolerance_does_not_move() -> None:
    pop, items, b = setup()
    a = person(pop)
    pop.confidence[a], pop.belief_tolerance[a], pop.knowledge[a] = 0.8, 0.3, 0.0
    far = item(items, sentiment=-0.9)
    r = b.absorb(np.array([far]), np.array([a]))
    assert pop.confidence[a] == 0.8 and r.blocked == 1 and r.moved == 0
    near = item(items, sentiment=0.95)
    b.absorb(np.array([near]), np.array([a]))
    assert 0.8 < pop.confidence[a] < 0.95


def test_step_matches_the_formula() -> None:
    pop, items, b = setup()
    a = person(pop)
    pop.confidence[a], pop.belief_tolerance[a] = 0.1, 1.2
    k, imp = 0.4, 0.3
    pop.knowledge[a], pop.impulsiveness[a] = k, imp
    s = item(items, sentiment=0.6, credibility=0.7, complexity=0.5, true_impact=0.03)
    b.absorb(np.array([s]), np.array([a]), trust=np.array([0.9]))
    alpha = k * (1 - 0.5 * (1 - k))
    eff = (1 - alpha) * 0.6 + alpha * np.clip(0.03 * CFG.belief.impact_to_sentiment, -1, 1)
    cred = (0.7 * 0.9) ** (1 + 2 * k)
    expect = 0.1 + CFG.belief.mu0 * (0.5 + imp) * (1 - 0.5 * k) * cred * (eff - 0.1)
    assert pop.confidence[a] == pytest.approx(expect)


def test_updates_of_one_tick_are_simultaneous() -> None:
    pop, items, b = setup()
    a = person(pop)
    pop.confidence[a], pop.belief_tolerance[a], pop.knowledge[a], pop.impulsiveness[a] = 0.0, 1.2, 0.0, 0.5
    s1, s2 = item(items, sentiment=0.5), item(items, sentiment=0.5)
    b.absorb(np.array([s1, s2]), np.array([a, a]))
    one = CFG.belief.mu0 * 1.0 * 0.8 * 0.5  # both steps computed from confidence 0
    assert pop.confidence[a] == pytest.approx(2 * one)


def test_real_event_moves_perceived_value_by_alpha() -> None:
    pop, items, b = setup()
    a = person(pop)
    pop.knowledge[a], pv = 0.5, float(pop.perceived_value[a])
    s = item(items, sentiment=-0.5, true_impact=-0.05, complexity=0.2)
    b.absorb(np.array([s]), np.array([a]))
    alpha = 0.5 * (1 - 0.2 * 0.5)
    assert pop.perceived_value[a] == pytest.approx(pv * np.exp(alpha * -0.05))
    rumour = item(items, sentiment=0.9, is_narrative=True)
    b.absorb(np.array([rumour]), np.array([a]))
    assert pop.perceived_value[a] == pytest.approx(pv * np.exp(alpha * -0.05))  # rumours have no impact


def test_media_have_no_beliefs() -> None:
    pop, items, b = setup()
    m = int(pop.media_ids[0])
    s = item(items, sentiment=0.9)
    b.absorb(np.array([s]), np.array([m]))
    b.drift()
    assert pop.confidence[m] == 0.0


def test_adopt_then_drop_after_a_denial() -> None:
    cfg = replace(CFG, belief=replace(CFG.belief, adopt_rate=1.0))
    pop, items, b = setup(cfg)
    a = person(pop)
    pop.confidence[a], pop.belief_tolerance[a], pop.knowledge[a], pop.impulsiveness[a] = 0.2, 1.2, 0.0, 1.0
    rumour = item(items, sentiment=0.8, is_narrative=True)
    r = b.absorb(np.array([rumour]), np.array([a]))
    assert r.adopted == 1 and pop.held_narrative[a] == items.item_id[rumour]
    assert pop.narrative_bias[a] == pytest.approx(cfg.belief.adopt_step * 0.8)
    pop.confidence[a] = 0.0
    for _ in range(20):
        b.drift()
    assert 0.05 < pop.confidence[a] < pop.narrative_bias[a]  # pulled toward the bias
    denial = item(items, sentiment=-0.4, parent=int(items.item_id[rumour]))
    r = b.absorb(np.array([denial]), np.array([a]))
    assert r.dropped == 1 and pop.held_narrative[a] == -1


def test_mutation_one_child_per_parent_with_handoff_factors() -> None:
    cfg = replace(CFG, diffusion=replace(CFG.diffusion, mutate_rate=1.0))
    pop, items, b = setup(cfg)
    people = np.flatnonzero(pop.category != MEDIA)[:40]
    pop.impulsiveness[people], pop.knowledge[people] = 1.0, 0.0
    parent = item(items, sentiment=0.6, credibility=0.5, salience=0.5, is_narrative=True)
    fact = item(items, sentiment=0.6)  # not a narrative: never mutates
    items.add_sharers(parent, people, start=1)
    items.add_sharers(fact, people, start=1)
    kids = b.mutate(0, np.r_[np.full(40, parent), np.full(40, fact)], np.r_[people, people])
    assert len(kids) == 1
    rec = items.lineage[kids[0]]
    assert (rec.origin, rec.parent, rec.root) == ("mutation", 0, 0)
    assert rec.sentiment == pytest.approx(0.84) and rec.credibility == pytest.approx(0.35)
    assert rec.salience == pytest.approx(0.6) and rec.is_narrative
    child = items.slot_of[kids[0]]
    assert set(items.live_sharers(child, 1)) == set(people)  # mutators seed the child
    assert len(items.live_sharers(parent, 1)) == 0  # ... and no longer share the parent
    assert len(items.live_sharers(fact, 1)) == 40


def test_invention_needs_a_big_unexplained_move_and_cools_down() -> None:
    cfg = replace(CFG, diffusion=replace(CFG.diffusion, invent_rate=0.5))
    pop, items, b = setup(cfg)
    online = np.ones(pop.n, bool)
    assert b.invent(40, 0.01, online) == -1  # below the threshold
    assert b.invent(41, 0.08, online) == -1  # not an hourly tick
    iid = b.invent(40, 0.08, online)
    rec = items.lineage[iid]
    assert rec.origin == "invention" and rec.sentiment > 0 and rec.is_narrative
    assert items.aware[items.slot_of[iid]].sum() > 0  # the inventors know it
    assert b.invent(44, 0.08, online) == -1  # one per direction per day
    down = b.invent(44, -0.08, online)
    assert down >= 0 and items.lineage[down].sentiment < 0
    assert b.invent(40 + 96, 0.08, online) >= 0  # next day


def test_agents_with_an_explanation_do_not_invent() -> None:
    cfg = replace(CFG, diffusion=replace(CFG.diffusion, invent_rate=1.0))
    pop, items, b = setup(cfg)
    everyone = np.arange(pop.n)
    item(items, sentiment=0.7, born=30, seeds=everyone)  # everybody already knows a bullish story
    assert b.invent(40, 0.1, np.ones(pop.n, bool)) == -1


def test_scripted_run_has_mutations_and_an_invention() -> None:
    cfg = Config(n_agents=10_000, seed=0)
    cfg = replace(cfg, diffusion=replace(cfg.diffusion, mutate_rate=0.2))
    pop = Population.build(cfg)
    graph = SocialGraph.build(pop, cfg.graph, np.random.default_rng(1))
    items = ItemStore(pop.n, cfg.diffusion.max_items, cfg.diffusion.retire_salience, cfg.diffusion.share_ttl)
    d = Diffusion(pop, graph, items, cfg, np.random.default_rng(2))
    b = Beliefs(pop, items, cfg, np.random.default_rng(3))
    ev = Event(96 + 40, "rumour", 0, 0.0, 0.8, 0.2, 0.9, 0.2, "influencer", id=0)
    conf0 = float(pop.confidence[pop.investor_ids].mean())
    for t in range(ev.tick, ev.tick + 2 * 96):
        if t == ev.tick:
            seeds = seed_agents(ev, pop, d.rng)
            slot = items.from_event(ev, t, seeds=seeds)
            b.absorb(np.full(len(seeds), slot), seeds)
        r = d.step(t)
        ret = -0.06 if ev.tick + 96 <= t < ev.tick + 96 + 24 else 0.0  # a big unexplained drop on day 2
        assert r.online_mask is not None
        seen = (r.seen_slots, r.seen_agents, r.seen_trust)
        b.step(t, *seen, r.share_slots, r.share_agents, r.online_mask, ret)
    origins = [rec.origin for rec in items.lineage]
    assert "mutation" in origins and "invention" in origins
    assert all(rec.parent >= 0 for rec in items.lineage if rec.origin == "mutation")
    assert items.lineage[origins.index("invention")].sentiment < 0
    assert (pop.held_narrative >= 0).sum() > 0
    assert np.abs(pop.confidence).max() <= 1.0
    # a bullish rumour that reached people leaves investors a little more bullish on average
    assert float(pop.confidence[pop.investor_ids].mean()) != conf0
