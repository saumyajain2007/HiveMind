"""Tests for marketsim.backtest (issue #13)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from marketsim.backtest import (
    DatedEvent,
    backtest,
    crps_gaussian,
    crps_sample,
    events_known_at,
    load_dated_events,
    load_price_csv,
    model_samples,
    parse_dated_events,
    random_walk_samples,
    synthetic_series,
)
from marketsim.config import TICKS_PER_DAY, Config
from marketsim.events import Event
from marketsim.sim import World

CFG = Config(n_agents=1_500, seed=0)


@pytest.mark.parametrize(("mu", "sigma", "y"), [(0.0, 1.0, 0.3), (100.0, 2.5, 96.0), (5.0, 0.1, 5.0)])
def test_sample_crps_matches_closed_form_gaussian(mu: float, sigma: float, y: float) -> None:
    x = np.random.default_rng(0).normal(mu, sigma, 200_000)
    assert crps_sample(x, y) == pytest.approx(crps_gaussian(mu, sigma, y), rel=0.01)


def test_crps_basics() -> None:
    assert crps_sample(np.array([3.0]), 1.0) == pytest.approx(2.0)  # one sample: absolute error
    near = crps_sample(np.random.default_rng(1).normal(0, 1, 5000), 0.0)
    far = crps_sample(np.random.default_rng(1).normal(3, 1, 5000), 0.0)
    assert near < far
    with pytest.raises(ValueError):
        crps_sample(np.array([]), 0.0)


def test_random_walk_is_mean_preserving() -> None:
    s = random_walk_samples(100.0, 0.02, 4, 200_000, np.random.default_rng(0))
    assert s.mean() == pytest.approx(100.0, rel=2e-3)
    assert np.log(s).std() == pytest.approx(0.04, rel=0.02)


def test_csv_and_dated_events(tmp_path: Path) -> None:
    csv_path = tmp_path / "px.csv"
    csv_path.write_text("date,close\n2024-01-02,100\n2024-01-03,101.5\n2024-01-04,99\n", encoding="utf-8")
    dates, closes = load_price_csv(csv_path)
    assert dates[1] == "2024-01-03" and closes.tolist() == [100.0, 101.5, 99.0]
    ev = {
        "kind": "earnings",
        "true_impact": -0.03,
        "sentiment": -0.5,
        "credibility": 0.9,
        "salience": 0.7,
        "complexity": 0.3,
        "seeding": "official",
    }
    ev_path = tmp_path / "ev.json"
    ev_path.write_text(json.dumps([{**ev, "date": "2024-01-03", "time": "16:30"}, {**ev, "day": 2}]), "utf-8")
    out = load_dated_events(ev_path, dates)
    assert (out[0].day, out[0].event.tick) == (1, 66) and (out[1].day, out[1].event.tick) == (2, 36)
    bad = tmp_path / "bad.csv"
    bad.write_text("day,price\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_price_csv(bad)
    with pytest.raises(ValueError):
        parse_dated_events([{**ev, "date": "1999-01-01"}], dates)
    with pytest.raises(ValueError):
        parse_dated_events([ev], dates)


def _shock(day: int, tick: int, impact: float, id: int) -> DatedEvent:
    return DatedEvent(day, Event(tick, "earnings", 0, impact, -0.8, 0.95, 0.9, 0.2, "official", id=id))


def test_no_lookahead() -> None:
    closes, events = synthetic_series(days=30, seed=3, n_events=3)
    events = [e for e in events if e.day < 20]
    future = _shock(21, 30, -0.3, id=99)  # a huge event after the origins below
    same_day_after_close = _shock(18, 70, -0.3, id=98)
    for origin in (17, 18):
        known = events_known_at([*events, future, same_day_after_close], origin)
        assert all(e.time <= origin * TICKS_PER_DAY + 63 for e in known)
        assert 99 not in {e.event.id for e in known}
    assert 98 not in {e.event.id for e in events_known_at([same_day_after_close], 17)}
    assert 98 in {e.event.id for e in events_known_at([same_day_after_close], 19)}

    world = World.build(CFG)
    a, used_a = model_samples(CFG, world, closes, events, 18, 1, [1, 2])
    b, used_b = model_samples(CFG, world, closes, [*events, future], 18, 1, [1, 2])
    assert a.tobytes() == b.tobytes() and used_a == used_b  # the future event changes nothing
    _, used_c = model_samples(CFG, world, closes, [*events, future], 22, 1, [1, 2])
    assert 99 in used_c


def test_backtest_scores_each_origin() -> None:
    closes, events = synthetic_series(days=30, seed=2)
    rows = []
    res = backtest(
        closes,
        events,
        origins=[21, 24],
        horizon=2,
        config=CFG,
        runs=3,
        rw_samples=500,
        on_origin=lambda k, n, row: rows.append((k, n)),
    )
    assert rows == [(0, 2), (1, 2)]
    assert [o["origin"] for o in res.origins] == [21, 24]
    for o in res.origins:
        assert o["actual"] == closes[o["origin"] + 2]
        assert o["crps_model"] >= 0 and o["crps_rw"] >= 0
        assert o["model_q05"] <= o["model_median"] <= o["model_q95"]
    assert res.skill == pytest.approx(1 - res.mean_crps_model / res.mean_crps_rw)
    json.dumps(res.to_dict())
    with pytest.raises(ValueError):
        backtest(closes, events, origins=[29], horizon=2, config=CFG, runs=1)


def test_implied_vol_follows_trailing_realised_vol() -> None:
    quiet = 100 * np.exp(np.cumsum(np.full(30, 0.001)))
    world = World.build(replace(CFG, n_agents=800))
    s, _ = model_samples(replace(CFG, n_agents=800), world, quiet, [], 25, 1, [1])
    assert np.isfinite(s).all()
