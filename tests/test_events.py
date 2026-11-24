"""Tests for marketsim.events (issue #4)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from marketsim.config import MEDIA, NON_INVESTOR, Config, MarketConfig
from marketsim.events import (
    Event,
    EventQueue,
    apply_to_market,
    broadcast_hits,
    event_from_dict,
    hawkes_events,
    hawkes_intensity,
    load_events,
    seed_agents,
)
from marketsim.market import MarketState
from marketsim.population import Population

BASE = {
    "tick": 10,
    "kind": "rumour",
    "sentiment": 0.8,
    "credibility": 0.2,
    "salience": 0.7,
    "complexity": 0.2,
    "seeding": "anonymous",
}


def ev(seeding: str, **kw: object) -> Event:
    d = {**BASE, "seeding": seeding, **kw}
    return event_from_dict(d)


@pytest.fixture(scope="module")
def pop() -> Population:
    return Population.build(Config(n_agents=20_000, seed=3))


# --------------------------------------------------------------------------- record + loading


def test_event_from_dict_defaults_and_flags() -> None:
    e = event_from_dict(BASE)
    assert (e.ticker, e.parent, e.id, e.topic, e.true_impact) == (0, -1, -1, "finance", 0.0)
    assert e.is_narrative and not e.is_real
    assert event_from_dict({**BASE, "kind": "earnings", "true_impact": -0.05}).is_real


@pytest.mark.parametrize(
    "bad",
    [
        {**BASE, "kind": "merger"},
        {**BASE, "kind": "price_move"},
        {**BASE, "seeding": "pigeon"},
        {**BASE, "topic": "gardening"},
        {**BASE, "sentiment": 1.5},  # strict: no clamping in files
        {**BASE, "credibility": "high"},
        {**BASE, "tick": -1},
        {**BASE, "tick": 1.5},
        {**BASE, "surprise": True},
        {k: v for k, v in BASE.items() if k != "salience"},
    ],
)
def test_event_from_dict_rejects(bad: dict) -> None:
    with pytest.raises(ValueError):
        event_from_dict(bad)


def test_price_move_allowed_internally() -> None:
    e = event_from_dict({**BASE, "kind": "price_move", "seeding": "outlet"}, allow_internal=True)
    assert e.kind == "price_move"


def test_load_events_list_and_object(tmp_path: Path) -> None:
    rumour = {**BASE, "label": "Takeover talk"}
    denial = {**BASE, "tick": 200, "kind": "statement", "seeding": "official", "parent": 0}
    p1 = tmp_path / "a.json"
    p1.write_text(json.dumps([rumour, denial]), encoding="utf-8")
    events = load_events(p1)
    assert [e.id for e in events] == [0, 1] and events[1].parent == 0
    p2 = tmp_path / "b.json"
    p2.write_text(json.dumps({"events": [{**BASE, "id": 7}]}), encoding="utf-8")
    assert load_events(p2)[0].id == 7


@pytest.mark.parametrize(
    "payload",
    [
        [{**BASE, "id": 1}, {**BASE, "id": 1}],  # duplicate ids
        [{**BASE, "parent": 5}],  # unknown parent
        [{**BASE, "id": 0, "tick": 50}, {**BASE, "id": 1, "tick": 10, "parent": 0}],  # parent later
        {"items": []},
    ],
)
def test_load_events_rejects(tmp_path: Path, payload: object) -> None:
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        load_events(p)


def test_queue_orders_by_tick_then_id() -> None:
    q = EventQueue([ev("anonymous", tick=5, id=3), ev("official", tick=2, id=9), ev("outlet", tick=5, id=1)])
    assert q.peek_tick() == 2 and len(q) == 3
    assert q.pop_due(1) == []
    assert [e.id for e in q.pop_due(5)] == [9, 1, 3]
    assert len(q) == 0 and q.peek_tick() is None
    added = q.push(ev("anonymous", tick=8))
    assert added.id == 10  # fresh id above every id seen


# --------------------------------------------------------------------------- Hawkes


def test_hawkes_intensity_formula() -> None:
    counts = np.array([0, 2, 0, 0, 1])
    lam = hawkes_intensity(counts, mu=0.1, alpha=0.5, beta=1.0)
    e = math.exp(-1.0)
    assert lam[:2] == pytest.approx([0.1, 0.1])
    assert lam[2] == pytest.approx(0.1 + 0.5 * 2 * e)
    assert lam[3] == pytest.approx(0.1 + 0.5 * 2 * e * e)


def test_hawkes_rate_rises_after_a_burst() -> None:
    rng = np.random.default_rng(0)
    T = 20_000
    events = hawkes_events(0.02, 0.4, 0.5, T, rng)
    counts = np.bincount([e.tick for e in events], minlength=T)
    lam = hawkes_intensity(counts, 0.02, 0.4, 0.5)
    after = np.flatnonzero(counts[:-3] > 0)
    window = np.mean([counts[t + 1 : t + 4].sum() for t in after])
    baseline = 3 * counts.mean()
    assert window > 1.5 * baseline  # arrivals cluster
    assert lam[after + 1].mean() > 2 * 0.02  # intensity jumps after an arrival
    # branching ratio n = alpha e^-beta / (1 - e^-beta) ≈ 0.62; stationary rate mu / (1 - n)
    n = 0.4 * math.exp(-0.5) / (1 - math.exp(-0.5))
    assert counts.mean() == pytest.approx(0.02 / (1 - n), rel=0.15)


def test_hawkes_attributes_are_valid_and_reproducible() -> None:
    a = hawkes_events(0.05, 0.2, 0.7, 2_000, np.random.default_rng(5), start_id=100)
    b = hawkes_events(0.05, 0.2, 0.7, 2_000, np.random.default_rng(5), start_id=100)
    assert a == b and len(a) > 50
    assert [e.id for e in a] == list(range(100, 100 + len(a)))
    for e in a:
        event_from_dict(e.to_dict())  # passes strict validation
        if e.kind == "rumour":
            assert e.true_impact == 0.0 and e.seeding in ("anonymous", "influencer")
    with pytest.raises(ValueError):
        hawkes_events(0.1, 0.2, 0.0, 10, np.random.default_rng(0))


# --------------------------------------------------------------------------- seeding


def test_seed_official(pop: Population) -> None:
    seeds = seed_agents(ev("official"), pop, np.random.default_rng(0))
    media = np.flatnonzero(pop.category == MEDIA)
    assert np.isin(media, seeds).all()
    investors = np.setdiff1d(seeds, media)
    n_inv = int(((pop.category != NON_INVESTOR) & (pop.category != MEDIA)).sum())
    assert len(investors) == math.ceil(0.005 * n_inv)
    assert (pop.category[investors] != NON_INVESTOR).all()
    assert pop.knowledge[investors].min() >= np.quantile(pop.knowledge[pop.investor_ids], 0.99)


def test_seed_outlet(pop: Population) -> None:
    media = np.flatnonzero(pop.category == MEDIA)
    for s in range(20):
        seeds = seed_agents(ev("outlet"), pop, np.random.default_rng(s))
        assert 3 <= len(seeds) <= min(10, len(media)) and np.isin(seeds, media).all()


def test_seed_influencer(pop: Population) -> None:
    people = np.flatnonzero(pop.category != MEDIA)
    cutoff = np.sort(pop.influence[people])[-math.ceil(0.001 * len(people))]
    for s in range(10):
        seeds = seed_agents(ev("influencer"), pop, np.random.default_rng(s))
        assert len(seeds) == 1 and pop.category[seeds[0]] != MEDIA
        assert pop.influence[seeds[0]] >= cutoff


def test_seed_insider_uses_connectedness(pop: Population) -> None:
    degree = np.zeros(pop.n)
    degree[pop.investor_ids[:50]] = 1_000  # make 50 investors by far the best connected
    seeds = seed_agents(ev("insider"), pop, np.random.default_rng(0), connectedness=degree)
    assert len(seeds) == 5 and np.isin(seeds, pop.investor_ids).all()
    fallback = seed_agents(ev("insider"), pop, np.random.default_rng(0))
    assert len(fallback) == 5 and np.isin(fallback, pop.investor_ids).all()


def test_seed_anonymous(pop: Population) -> None:
    people = np.flatnonzero(pop.category != MEDIA)
    med = np.median(pop.influence[people])
    for s in range(10):
        seeds = seed_agents(ev("anonymous"), pop, np.random.default_rng(s))
        assert len(seeds) == 1 and pop.influence[seeds[0]] <= med and pop.category[seeds[0]] != MEDIA


def test_broadcast_hits_rate() -> None:
    attention = np.full(100_000, 0.5)
    hits = broadcast_hits(0.8, attention, 0.15, np.random.default_rng(0))
    assert len(hits) / len(attention) == pytest.approx(0.8 * 0.5 * 0.15, rel=0.05)
    assert len(broadcast_hits(0.0, attention, 0.15, np.random.default_rng(0))) == 0


def test_real_event_moves_fundamental_value() -> None:
    m = MarketState(MarketConfig())
    apply_to_market(ev("official", kind="earnings", true_impact=-0.05), m)
    assert m.v_true == pytest.approx(100 * math.exp(-0.05))
    apply_to_market(ev("anonymous"), m)  # a rumour has no true impact
    assert m.v_true == pytest.approx(100 * math.exp(-0.05))
