"""Tests for marketsim.items (issue #5)."""

from __future__ import annotations

import numpy as np
import pytest

from marketsim.events import Event
from marketsim.items import ItemStore


def make(store: ItemStore, born: int = 0, parent: int = -1, salience: float = 0.5, **kw: object) -> int:
    return store.create(
        sentiment=0.5,
        credibility=0.5,
        salience=salience,
        complexity=0.2,
        born=born,
        origin=kw.pop("origin", "event"),
        parent=parent,
        **kw,  # type: ignore[arg-type]
    )


def test_create_sets_attributes_and_lineage() -> None:
    st = ItemStore(n_agents=100, max_items=4)
    slot = st.create(
        sentiment=1.7,
        credibility=0.3,
        salience=0.6,
        complexity=0.4,
        born=12,
        origin="event",
        true_impact=-0.05,
        topic="tech",
        is_narrative=True,
        event_id=3,
        kind="rumour",
        label="x",
        seeds=np.array([5, 5, 9]),
    )
    rec = st.lineage[0]
    assert st.item_id[slot] == 0 and st.slot_of[0] == slot
    assert st.sentiment[slot] == 1.0  # clipped
    assert (rec.parent, rec.root, rec.origin, rec.born, rec.event_id) == (-1, 0, "event", 12, 3)
    assert st.aware[slot, [5, 9]].all() and st.aware[slot].sum() == 2
    assert st.shared[slot, [5, 9]].all() and rec.total_shares == 2
    assert st.live_sharers(slot, 12).tolist() == [5, 9]  # seeds share from birth
    with pytest.raises(ValueError):
        make(st, origin="gossip")
    with pytest.raises(ValueError):
        make(st, parent=99)


def test_sharers_live_for_ttl_and_share_once() -> None:
    st = ItemStore(n_agents=50, max_items=2, share_ttl=4)
    slot = make(st)
    added = st.add_sharers(slot, np.array([1, 2, 2]), start=10)
    assert added.tolist() == [1, 2]
    assert st.add_sharers(slot, np.array([2, 3]), start=11).tolist() == [3]  # 2 already shared
    assert st.live_sharers(slot, 9).tolist() == []
    assert st.live_sharers(slot, 10).tolist() == [1, 2]
    assert sorted(st.live_sharers(slot, 13).tolist()) == [1, 2, 3]
    assert st.live_sharers(slot, 14).tolist() == [3]  # first batch expired
    assert st.starting_sharers(slot, 11).tolist() == [3]
    assert st.has_pending_shares(slot, 14) and not st.has_pending_shares(slot, 15)
    assert st.lineage[0].total_shares == 3


def test_retirement_waits_for_fade_and_feeds() -> None:
    st = ItemStore(n_agents=10, max_items=2, retire_salience=0.05, share_ttl=3)
    slot = make(st, salience=0.04, seeds=np.array([1]))  # faded, but its seed is still in feeds
    assert st.retire_eligible(tick=1) == []
    assert st.retire_eligible(tick=3, keep={0}) == []  # held (e.g. pending YouTube upload)
    assert st.retire_eligible(tick=3) == [0]
    assert not st.active[slot] and st.lineage[0].retired == 3 and st.lineage[0].final_aware == 1


def test_slot_reuse_never_leaks_awareness() -> None:
    rng = np.random.default_rng(0)
    st = ItemStore(n_agents=500, max_items=4, retire_salience=0.1, share_ttl=1)
    expected = []
    for i in range(1_200):
        slot = make(st, born=i, salience=0.5)
        assert not st.aware[slot].any() and not st.shared[slot].any()  # clean slot
        who = np.unique(rng.integers(0, 500, rng.integers(0, 40)))
        st.mark_aware(np.full(len(who), slot), who)
        expected.append(len(who))
        st.salience[slot] = 0.0
        assert st.retire_eligible(tick=i + 5) == [i]
    assert len(st.lineage) == 1_200
    assert [r.final_aware for r in st.lineage] == expected
    assert st.evicted == 0 and not st.active.any()


def test_full_store_evicts_faintest() -> None:
    st = ItemStore(n_agents=10, max_items=3)
    for s in (0.9, 0.2, 0.6):
        make(st, salience=s)
    make(st, born=5, salience=0.8)
    assert st.evicted == 1
    assert st.lineage[1].retired == 5  # salience 0.2 was dropped
    assert sorted(int(st.item_id[s]) for s in st.active_slots()) == [0, 2, 3]


def test_family_tree_and_family_awareness() -> None:
    st = ItemStore(n_agents=20, max_items=8)
    root = make(st, seeds=np.array([0]))
    child = make(st, parent=0, origin="mutation", seeds=np.array([1]))
    grand = make(st, parent=1, origin="mutation")
    other = make(st, seeds=np.array([5]))
    st.mark_aware(np.array([grand, grand]), np.array([2, 0]))
    assert st.family_of(0) == [0, 1, 2]
    assert st.family_of(3) == [3]
    assert st.lineage[2].root == 0 and st.root[grand] == 0
    assert st.family_aware_count(0) == 3  # agents 0, 1, 2 (0 counted once)
    assert st.family_aware_count(3) == 1
    assert {root, child, grand, other} == set(range(4))


def test_follow_up_event_hangs_under_its_parents_item() -> None:
    st = ItemStore(n_agents=10, max_items=4)
    rumour = Event(5, "rumour", 0, 0.0, 0.8, 0.2, 0.7, 0.2, "anonymous", id=10)
    denial = Event(90, "statement", 0, 0.0, -0.3, 0.9, 0.5, 0.2, "official", parent=10, id=11)
    move = Event(95, "price_move", 0, 0.0, -0.6, 0.85, 0.6, 0.1, "outlet", id=12)
    s1 = st.from_event(rumour, 5)
    s2 = st.from_event(denial, 90)
    s3 = st.from_event(move, 95)
    assert st.is_narrative[s1] and not st.is_narrative[s2]
    assert st.lineage[1].parent == 0 and st.family_of(0) == [0, 1]
    assert st.lineage[2].origin == "price_news"
    assert not st.broadcast[s1] and st.broadcast[s2] and st.broadcast[s3]


def test_resize_adds_agents() -> None:
    st = ItemStore(n_agents=5, max_items=2)
    slot = make(st, seeds=np.array([4]))
    st.resize(8)
    assert st.aware.shape == (2, 8) and st.shared.shape == (2, 8)
    assert st.aware[slot, 4] and not st.aware[slot, 5:].any()
    assert st.family_aware[0].shape == (8,)
    st.mark_aware(np.array([slot]), np.array([7]))
    assert st.family_aware_count(0) == 2
    with pytest.raises(ValueError):
        st.resize(3)
