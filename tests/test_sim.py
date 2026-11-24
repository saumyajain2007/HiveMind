"""Tests for marketsim.sim (issue #10)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pytest

from marketsim.config import ALL_PLATFORMS, CATEGORIES, TICKS_PER_DAY, Config
from marketsim.sim import FAMILY_COLUMNS, Scenario, Simulation, World, load, save

CFG = Config(n_agents=3_000, seed=0)
DEMO = [
    {
        "tick": 44,
        "kind": "rumour",
        "sentiment": 0.8,
        "credibility": 0.2,
        "salience": 0.9,
        "complexity": 0.2,
        "seeding": "influencer",
        "label": "Takeover talk",
    },
    {
        "tick": 96 + 40,
        "kind": "statement",
        "sentiment": -0.6,
        "credibility": 0.95,
        "salience": 0.7,
        "complexity": 0.1,
        "seeding": "official",
        "parent": 0,
        "label": "Company denies",
    },
    {
        "tick": 2 * 96 + 39,
        "kind": "earnings",
        "true_impact": -0.05,
        "sentiment": -0.7,
        "credibility": 0.95,
        "salience": 0.8,
        "complexity": 0.4,
        "seeding": "official",
    },
]


@pytest.fixture(scope="module")
def world() -> World:
    return World.build(CFG)


def scenario() -> Scenario:
    return Scenario.from_dicts(DEMO)


def run(world: World, seed: int = 1, ticks: int = 3 * TICKS_PER_DAY, **kw: object) -> dict:
    return Simulation(CFG, scenario(), seed, world=world, **kw).run(ticks)  # type: ignore[arg-type]


def test_same_seed_gives_identical_results(world: World) -> None:
    a, b = run(world), run(world)
    for k in a["series"]:
        assert a["series"][k].tobytes() == b["series"][k].tobytes(), k
    for k in ("awareness", "family", "ohlc"):
        assert a[k].tobytes() == b[k].tobytes(), k
    for k in ("lineage", "events", "summary", "meta"):
        assert json.dumps(a[k]) == json.dumps(b[k]), k
    c = run(world, seed=2)
    assert c["series"]["price"].tobytes() != a["series"]["price"].tobytes()


def test_world_is_not_changed_by_a_run(world: World) -> None:
    before = world.pop.confidence.copy(), world.pop.shares.copy()
    run(world, ticks=TICKS_PER_DAY)
    assert np.array_equal(world.pop.confidence, before[0]) and np.array_equal(world.pop.shares, before[1])


def test_results_shape_and_metrics(world: World) -> None:
    r = run(world)
    T = 3 * TICKS_PER_DAY
    assert all(len(v) == T for v in r["series"].values())
    assert r["ohlc"].shape == (3, 4)
    assert r["meta"]["n_ticks"] == T and not r["meta"]["cancelled"]
    fam = r["family"]
    assert fam.shape[1] == len(FAMILY_COLUMNS)
    total = fam[:, 2]
    plats = fam[:, 3 : 3 + len(ALL_PLATFORMS)]
    cats = fam[:, 3 + len(ALL_PLATFORMS) :]
    assert (plats <= total[:, None]).all() and (cats.sum(axis=1) == total).all()
    assert cats.shape[1] == len(CATEGORIES)
    # the rumour family holds the rumour and the denial hanging under it
    fams = {f["root"]: f for f in r["summary"]["families"]}
    rumour = r["events"][0]["item"]
    assert fams[rumour]["members"] >= 2 and fams[rumour]["label"] == "Takeover talk"
    denial = next(rec for rec in r["lineage"] if rec["kind"] == "statement")
    assert denial["parent"] == rumour and denial["root"] == rumour
    # the earnings miss moved V_true
    # real events move V_true by exactly their true impact; the informed share of the unmodelled
    # flow (market.noise_permanence) adds a small random walk on top
    assert r["series"]["v_true"][-1] == pytest.approx(100 * np.exp(-0.05), rel=0.02)
    json.dumps(r["summary"])  # valid JSON (NaN replaced)


def test_big_moves_become_price_news() -> None:
    cfg = Config(n_agents=3_000, seed=0)
    shock = [{**DEMO[2], "true_impact": -0.4, "tick": 39}]
    sim = Simulation(cfg, Scenario.from_dicts(shock), seed=3)
    r = sim.run(TICKS_PER_DAY)
    news = [e for e in r["events"] if e["kind"] == "price_move"]
    assert news, "a 40% fundamental shock should make the price move past the headline threshold"
    assert news[0]["label"].startswith("Stock ") and news[0]["seeding"] == "outlet"
    assert any(rec["origin"] == "price_news" for rec in r["lineage"])


def test_on_tick_frames_and_cancellation(world: World) -> None:
    frames: list[dict] = []
    sample = np.arange(0, world.pop.n, 10)
    sim = Simulation(CFG, scenario(), 1, world=world, on_tick=frames.append, node_sample=sample)
    sim.run(2 * TICKS_PER_DAY)
    assert [f["tick"] for f in frames] == list(range(2 * TICKS_PER_DAY))
    json.dumps(frames)  # JSON-ready
    born = [m for f in frames for m in f["born"]]
    assert {m["type"] for m in born} >= {"event"}
    first = next(m for m in born if m["type"] == "event")
    assert (first["tick"], first["kind"], first["label"]) == (44, "rumour", "Takeover talk")
    # node_seen agrees with awareness of the sampled nodes
    seen = {(i, iid) for f in frames for i, iid in f["node_seen"]}
    rumour_item = first["item"]
    aware = sim.items.family_aware[rumour_item][sample]
    lit = {i for i, iid in seen if sim.items.lineage[iid].root == rumour_item}
    assert lit <= set(np.flatnonzero(aware).tolist())
    stop_after = 50
    calls = {"n": 0}

    def should_stop() -> bool:
        calls["n"] += 1
        return calls["n"] > stop_after

    r = Simulation(CFG, scenario(), 1, world=world, should_stop=should_stop).run(TICKS_PER_DAY)
    assert r["meta"]["cancelled"] and r["meta"]["n_ticks"] == stop_after


def test_save_and_load_round_trip(world: World, tmp_path: Path) -> None:
    r = run(world, ticks=TICKS_PER_DAY)
    save(r, tmp_path / "run")
    back = load(tmp_path / "run")
    for k in r["series"]:
        assert np.array_equal(back["series"][k], r["series"][k])
    for k in ("awareness", "family", "ohlc"):
        assert np.array_equal(back[k], r[k])
    for k in ("lineage", "events", "summary", "meta"):
        assert back[k] == json.loads(json.dumps(r[k]))


def test_five_day_run_at_10k_is_fast_and_alive() -> None:
    cfg = Config(n_agents=10_000, seed=0)
    t0 = time.perf_counter()
    sim = Simulation(cfg, Scenario.from_dicts(DEMO), seed=1)
    r = sim.run(5 * TICKS_PER_DAY)
    elapsed = time.perf_counter() - t0
    assert elapsed < 30.0
    p = r["series"]["price"]
    assert r["series"]["volume"].sum() > 0 and p.max() / p.min() > 1.005
    assert r["summary"]["n_event"] == 3


def test_on_tick_overhead_is_small(world: World) -> None:
    def timed(**kw: object) -> float:
        best = float("inf")
        for _ in range(5):
            t0 = time.perf_counter()
            run(world, ticks=TICKS_PER_DAY, **kw)
            best = min(best, time.perf_counter() - t0)
        return best

    plain = timed()
    framed = timed(on_tick=lambda f: None)
    assert framed < plain * 1.5  # target < 5% (measured in DECISIONS); loose bound for CI noise
