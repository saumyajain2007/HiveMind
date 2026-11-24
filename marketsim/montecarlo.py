"""Monte Carlo price-path distribution (issue #11, HANDOFF §4 M4 `montecarlo.py`).

The population and graph (the *world*, from `config.seed`) are built once; R runs differ only in
their dynamics seed. Runs can be spread over worker processes; results are identical to a
serial run because every run is fully determined by (config, scenario, seed).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .config import TICKS_PER_DAY, Config
from .metrics import acf, excess_kurtosis, open_tick_returns
from .sim import Scenario, Simulation, World, json_safe
from .sim import load as load_run
from .sim import save as save_run

QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)
ProgressFn = Callable[[int, int, dict[str, np.ndarray]], None]


@dataclass
class MonteCarloResult:
    seeds: list[int]
    paths: np.ndarray  # (R, T) price
    v_true: np.ndarray  # (R, T)
    volume: np.ndarray  # (R, T)
    confidence: np.ndarray  # (R, T)
    summaries: list[dict[str, Any]]
    event_reach: list[dict[str, float]]  # per run: scenario event id -> final family share
    representative: dict[str, Any] | None = None  # full results of the median-final-price run
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def n_runs(self) -> int:
        return len(self.paths)

    def quantiles(self, qs: Sequence[float] = QUANTILES) -> dict[str, np.ndarray]:
        return quantile_bands(self.paths, qs)

    def summary(self) -> dict[str, Any]:
        """Distribution-level numbers, including the pooled stylised facts (reported only)."""
        p = self.paths
        p0 = p[:, 0]
        final = p[:, -1]
        rets = [open_tick_returns(row) for row in p]
        pooled = np.concatenate(rets) if rets else np.zeros(0)
        acf_r = np.nanmean([acf(r, 10) for r in rets], axis=0) if rets else np.full(10, np.nan)
        acf_abs = np.nanmean([acf(np.abs(r), 10) for r in rets], axis=0) if rets else np.full(10, np.nan)
        log_ret = np.log(final / p0)
        reach: dict[str, list[float]] = {}
        for run in self.event_reach:
            for k, v in run.items():
                reach.setdefault(k, []).append(v)
        return json_safe(
            {
                "n_runs": self.n_runs,
                "n_ticks": int(p.shape[1]),
                "days": p.shape[1] / TICKS_PER_DAY,
                "initial_price": float(p0.mean()),
                "final_price_quantiles": {f"{q:g}": float(np.quantile(final, q)) for q in QUANTILES},
                "v_true_final": float(self.v_true[:, -1].mean()),
                "p_below_start": float((final < p0).mean()),
                "final_price": float(np.median(final)),
                "return": float(np.median(final / p0) - 1.0),
                "price_spark": [
                    round(float(np.median(p[:, t])), 4) for t in range(63, p.shape[1], TICKS_PER_DAY)
                ],
                "mean_log_return": float(log_ret.mean()),
                "var_95": float(-np.quantile(final / p0 - 1.0, 0.05)),
                "median_max_drawdown": float(np.median([s["max_drawdown"] for s in self.summaries])),
                "mean_volume_per_day": float(
                    self.volume.sum(axis=1).mean() / max(p.shape[1] / TICKS_PER_DAY, 1e-9)
                ),
                "event_reach_median": {k: float(np.median(v)) for k, v in reach.items()},
                "stylized_facts": {
                    "n_returns": len(pooled),
                    "return_sd": float(pooled.std()) if len(pooled) else 0.0,
                    "excess_kurtosis": excess_kurtosis(pooled),
                    "acf_r": acf_r.tolist(),
                    "acf_abs_r": acf_abs.tolist(),
                },
                **self.meta,
            }
        )


def quantile_bands(paths: np.ndarray, qs: Sequence[float] = QUANTILES) -> dict[str, np.ndarray]:
    return {f"{q:g}": np.quantile(paths, q, axis=0) for q in qs}


# --------------------------------------------------------------------------- one run

_WORLD: World | None = None  # per worker process


def _init_worker(cfg: Config) -> None:
    global _WORLD
    _WORLD = World.build(cfg)


def _event_reach(res: dict[str, Any], n: int) -> dict[str, float]:
    out = {}
    fams = {f["root"]: f for f in res["summary"]["families"]}
    for ev in res["events"]:
        if ev["kind"] == "price_move":
            continue
        root = res["lineage"][ev["item"]]["root"]
        if root in fams:
            out[str(ev["id"])] = fams[root]["aware"] / n
    return out


def _one(cfg: Config, scenario: Scenario, seed: int, n_ticks: int, world: World | None) -> dict[str, Any]:
    world = world or _WORLD
    sim = Simulation(cfg, scenario, seed, world=world)
    return sim.run(n_ticks)


def _run_job(args: tuple[Config, Scenario, int, int]) -> dict[str, Any]:
    cfg, scenario, seed, n_ticks = args
    return _one(cfg, scenario, seed, n_ticks, None)


# --------------------------------------------------------------------------- the runner


def run(
    config: Config,
    scenario: Scenario | None = None,
    R: int = 20,
    workers: int = 1,
    *,
    n_ticks: int | None = None,
    seeds: Sequence[int] | None = None,
    progress: ProgressFn | None = None,
    should_stop: Callable[[], bool] | None = None,
    progress_every: int = 1,
    world: World | None = None,
) -> MonteCarloResult:
    """R dynamics seeds on one world. `progress(done, R, partial_quantiles)` is called every
    `progress_every` finished runs (and at the end); `should_stop()` stops early."""
    scenario = scenario or Scenario()
    T = 5 * TICKS_PER_DAY if n_ticks is None else int(n_ticks)
    seeds = list(range(1, R + 1)) if seeds is None else list(seeds)
    R = len(seeds)
    results: dict[int, dict[str, Any]] = {}

    def done(i: int, res: dict[str, Any]) -> None:
        results[i] = res
        if progress is not None and (len(results) % progress_every == 0 or len(results) == R):
            part = np.stack([results[k]["series"]["price"] for k in sorted(results)])
            progress(len(results), R, quantile_bands(part))

    if workers <= 1:
        w = world or World.build(config)
        for i, s in enumerate(seeds):
            if should_stop is not None and should_stop():
                break
            done(i, _one(config, scenario, s, T, w))
    else:
        with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker, initargs=(config,)) as ex:
            futures = {ex.submit(_run_job, (config, scenario, s, T)): i for i, s in enumerate(seeds)}
            for fut in futures:  # in submission order, so progress is deterministic
                if should_stop is not None and should_stop():
                    for f in futures:
                        f.cancel()
                    break
                done(futures[fut], fut.result())

    order = sorted(results)
    runs = [results[i] for i in order]
    if not runs:
        raise RuntimeError("no Monte Carlo run finished")
    stack = {k: np.stack([r["series"][k] for r in runs]) for k in ("price", "v_true", "volume", "confidence")}
    n_nodes = runs[0]["meta"]["n_nodes"]
    final = stack["price"][:, -1]
    median_run = int(np.argsort(final)[len(final) // 2])
    return MonteCarloResult(
        seeds=[seeds[i] for i in order],
        paths=stack["price"],
        v_true=stack["v_true"],
        volume=stack["volume"],
        confidence=stack["confidence"],
        summaries=[{**r["summary"], "seed": seeds[i]} for i, r in zip(order, runs, strict=True)],
        event_reach=[_event_reach(r, n_nodes) for r in runs],
        representative=runs[median_run],
        meta={
            "n_agents": config.n_agents,
            "world_seed": config.seed,
            "workers": workers,
            "stopped_early": len(runs) < R,
            "representative_seed": seeds[order[median_run]],
        },
    )


# --------------------------------------------------------------------------- io


def save(mc: MonteCarloResult, path: str | Path) -> Path:
    """`paths.npy` (R, T) and `montecarlo.npz` (all arrays + quantiles), `montecarlo.json`
    (seeds, per-run summaries, distribution summary) and the representative run in `rep/`."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    np.save(path / "paths.npy", mc.paths)
    q = mc.quantiles()
    arrays: dict[str, Any] = {
        "paths": mc.paths,
        "v_true": mc.v_true,
        "volume": mc.volume,
        "confidence": mc.confidence,
        **{f"q_{k}": v for k, v in q.items()},
    }
    np.savez_compressed(path / "montecarlo.npz", **arrays)
    doc = {
        "seeds": mc.seeds,
        "summaries": mc.summaries,
        "event_reach": mc.event_reach,
        "meta": mc.meta,
        "summary": mc.summary(),
    }
    (path / "montecarlo.json").write_text(json.dumps(json_safe(doc), indent=1), encoding="utf-8")
    if mc.representative is not None:
        save_run(mc.representative, path / "rep")
    return path


def load(path: str | Path) -> MonteCarloResult:
    path = Path(path)
    doc = json.loads((path / "montecarlo.json").read_text(encoding="utf-8"))
    with np.load(path / "montecarlo.npz") as z:
        arrays = {k: z[k] for k in ("paths", "v_true", "volume", "confidence")}
    rep = load_run(path / "rep") if (path / "rep").exists() else None
    return MonteCarloResult(
        seeds=doc["seeds"],
        summaries=doc["summaries"],
        event_reach=doc["event_reach"],
        representative=rep,
        meta=doc["meta"],
        **arrays,
    )
