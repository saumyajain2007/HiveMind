"""Tests for marketsim.calibration (issue #12)."""

from __future__ import annotations

import numpy as np
import pytest

from marketsim import scenarios
from marketsim.calibration import (
    calibrate,
    format_recovery,
    median_log_path,
    recovery_test,
    rmse,
    with_params,
)
from marketsim.config import TICKS_PER_DAY, Config
from marketsim.sim import World

CFG = Config(n_agents=1_500, seed=0)


def test_with_params_sets_fields_in_their_sections() -> None:
    c = with_params(CFG, {"impact_Y": 0.5, "base_share": 0.4, "mu0": 0.2, "sentiment_scale": 0.03})
    assert (c.market.impact_Y, c.diffusion.base_share, c.belief.mu0, c.trading.sentiment_scale) == (
        0.5,
        0.4,
        0.2,
        0.03,
    )
    assert with_params(CFG, {"market.noise_frac": 0.1}).market.noise_frac == 0.1
    assert CFG.market.impact_Y == 0.7  # the original is untouched
    with pytest.raises(KeyError):
        with_params(CFG, {"market.nope": 1.0})


def test_calibrate_logs_trials_and_keeps_the_best() -> None:
    world = World.build(CFG)
    obs = median_log_path(CFG, scenarios.demo(), [5], TICKS_PER_DAY, world)
    seen = []
    res = calibrate(
        obs,
        scenarios.demo(),
        {"impact_Y": (0.4, 1.2)},
        n_trials=4,
        runs_per_trial=1,
        config=CFG,
        world=world,
        on_trial=lambda i, n, t: seen.append((i, n, t["rmse"])),
    )
    assert [s[0] for s in seen] == [0, 1, 2, 3] and all(s[1] == 4 for s in seen)
    errs = [t["rmse"] for t in res.trials]
    assert res.best_rmse == min(errs)
    assert res.best == res.trials[int(np.argmin(errs))]["params"]
    assert 0.4 <= res.best["impact_Y"] <= 1.2
    assert len(res.best_path) == len(obs) and set(res.sensitivity()) == {"impact_Y"}
    d = res.to_dict()
    assert d["best_rmse"] == res.best_rmse and len(d["trials"]) == 4
    # deterministic: same seed, same trials
    again = calibrate(
        obs, scenarios.demo(), {"impact_Y": (0.4, 1.2)}, n_trials=4, runs_per_trial=1, config=CFG, world=world
    )
    assert [t["rmse"] for t in again.trials] == errs


def test_calibrate_stops_early() -> None:
    calls = {"n": 0}

    def stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 2

    obs = np.zeros(TICKS_PER_DAY // 2)
    res = calibrate(obs, None, n_trials=10, runs_per_trial=1, config=CFG, should_stop=stop)
    assert len(res.trials) == 2


def test_recovery_test_end_to_end() -> None:
    rep = recovery_test(n_trials=3, runs_per_trial=1, n_agents=1_000, days=1)
    assert [r["parameter"] for r in rep["rows"]] == ["impact_Y", "base_share", "mu0", "sentiment_scale"]
    for r in rep["rows"]:
        assert r["error"] == pytest.approx(r["recovered"] - r["true"])
    table = format_recovery(rep)
    assert table.startswith("| parameter |") and "observed = one path." in table


def test_rmse() -> None:
    assert rmse(np.array([0.0, 1.0]), np.array([0.0, 0.0, 5.0])) == pytest.approx(np.sqrt(0.5))


def test_calibrate_on_daily_closes_relative() -> None:
    world = World.build(CFG)
    path = median_log_path(CFG, scenarios.demo(), [5], 2 * TICKS_PER_DAY, world)
    ticks = [63, 96 + 63]
    obs = path[ticks] + 3.0  # a different price level: relative mode ignores it
    res = calibrate(
        obs,
        scenarios.demo(),
        {"impact_Y": (0.6, 0.8)},
        n_trials=2,
        runs_per_trial=1,
        config=CFG,
        world=world,
        observed_ticks=ticks,
        relative=True,
    )
    assert len(res.best_path) == 2 and res.best_path[0] == 0.0 and res.observed[0] == 0.0
    with pytest.raises(ValueError):
        calibrate(obs, None, n_trials=1, config=CFG, world=world, observed_ticks=[63])
