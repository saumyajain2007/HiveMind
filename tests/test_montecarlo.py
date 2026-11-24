"""Tests for marketsim.montecarlo, viz and run_demo (issue #11)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from marketsim import montecarlo, run_demo, scenarios, viz
from marketsim.config import TICKS_PER_DAY, Config
from marketsim.sim import World

CFG = Config(n_agents=2_000, seed=0)
T = 2 * TICKS_PER_DAY


@pytest.fixture(scope="module")
def world() -> World:
    return World.build(CFG)


@pytest.fixture(scope="module")
def mc(world: World) -> montecarlo.MonteCarloResult:
    return montecarlo.run(CFG, scenarios.demo(), R=5, n_ticks=T, world=world)


def test_paths_and_quantiles(mc: montecarlo.MonteCarloResult) -> None:
    assert mc.paths.shape == (5, T) and mc.v_true.shape == (5, T)
    q = mc.quantiles()
    stacked = np.stack([q[k] for k in ("0.05", "0.25", "0.5", "0.75", "0.95")])
    assert np.all(np.diff(stacked, axis=0) >= -1e-12)  # bands are ordered
    assert len({row.tobytes() for row in mc.paths}) == 5  # every seed gives its own path
    s = mc.summary()
    assert s["n_runs"] == 5 and len(s["stylized_facts"]["acf_abs_r"]) == 10
    assert "0" in s["event_reach_median"]  # the rumour's family reach
    json.dumps(s)
    assert mc.representative is not None and mc.meta["representative_seed"] in mc.seeds


def test_same_seeds_same_paths_serial_or_parallel(world: World, mc: montecarlo.MonteCarloResult) -> None:
    again = montecarlo.run(CFG, scenarios.demo(), R=5, n_ticks=T, world=world)
    assert again.paths.tobytes() == mc.paths.tobytes()
    par = montecarlo.run(CFG, scenarios.demo(), seeds=[1, 2], n_ticks=T, workers=2)
    assert par.paths.tobytes() == mc.paths[:2].tobytes()


def test_progress_and_stop(world: World) -> None:
    seen: list[tuple[int, int]] = []

    def progress(done: int, total: int, q: dict) -> None:
        seen.append((done, total))
        assert q["0.5"].shape == (TICKS_PER_DAY,)

    montecarlo.run(CFG, scenarios.demo(), R=3, n_ticks=TICKS_PER_DAY, world=world, progress=progress)
    assert seen == [(1, 3), (2, 3), (3, 3)]
    calls = {"n": 0}

    def stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 2

    r = montecarlo.run(CFG, scenarios.demo(), R=5, n_ticks=TICKS_PER_DAY, world=world, should_stop=stop)
    assert r.n_runs == 2 and r.meta["stopped_early"]


def test_save_load(mc: montecarlo.MonteCarloResult, tmp_path: Path) -> None:
    montecarlo.save(mc, tmp_path / "mc")
    assert (tmp_path / "mc" / "paths.npy").exists()
    back = montecarlo.load(tmp_path / "mc")
    assert np.array_equal(back.paths, mc.paths) and back.seeds == mc.seeds
    assert back.representative is not None
    assert back.summary()["final_price_quantiles"] == mc.summary()["final_price_quantiles"]


def test_plots_are_written(mc: montecarlo.MonteCarloResult, world: World, tmp_path: Path) -> None:
    paths = viz.all_plots(mc, tmp_path, world.pop.category, world.pop.platform_use)
    assert {p.name for p in paths} == {
        "fan_chart.png",
        "stylized_facts.png",
        "family_awareness.png",
        "awareness_breakdown.png",
        "lineage_tree.png",
    }
    assert all(p.stat().st_size > 10_000 for p in paths)


def test_run_demo_cli(tmp_path: Path) -> None:
    out = tmp_path / "out"
    summary = run_demo.main(
        ["--agents", "1500", "--days", "1", "--runs", "2", "--workers", "1", "--out", str(out)]
    )
    doc = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert doc["n_runs"] == 2 and summary["n_runs"] == 2
    sf = doc["stylized_facts"]
    assert "excess_kurtosis" in sf and len(sf["acf_abs_r"]) == 10
    assert len(list(out.glob("*.png"))) == 5
