"""Calibration by random search, and the parameter-recovery test (issue #12, HANDOFF §4 M5).

`calibrate` draws parameter sets uniformly inside `param_space`, runs `runs_per_trial` dynamics
seeds for each, and scores the *median* simulated log-price path against the observed one by
RMSE. Every trial uses the same seeds (common random numbers), so differences between trials
come from the parameters, not from luck.

`recovery_test` is the identifiability check: it simulates "observed" prices from known
parameters, calibrates on them, and reports how close each recovered parameter is.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from .config import TICKS_PER_DAY, Config
from .sim import Scenario, Simulation, World

# The handoff's four parameters, and the config section each lives in.
DEFAULT_SPACE: dict[str, tuple[float, float]] = {
    "impact_Y": (0.3, 1.5),
    "base_share": (0.1, 0.5),
    "mu0": (0.1, 0.7),
    "sentiment_scale": (0.01, 0.10),
}
SECTIONS = {
    "impact_Y": "market",
    "base_share": "diffusion",
    "mu0": "belief",
    "sentiment_scale": "trading",
}
TrialFn = Callable[[int, int, dict[str, Any]], None]


def with_params(cfg: Config, params: Mapping[str, float]) -> Config:
    """Copy of `cfg` with parameters set. Names are fields of SECTIONS or "section.field"."""
    out = cfg
    for name, value in params.items():
        section, key = name.split(".", 1) if "." in name else (SECTIONS[name], name)
        sub = getattr(out, section)
        if not hasattr(sub, key):
            raise KeyError(f"unknown parameter {name!r}")
        cur = getattr(sub, key)
        out = replace(out, **{section: replace(sub, **{key: type(cur)(value)})})
    return out


def median_log_path(
    cfg: Config, scenario: Scenario, seeds: Sequence[int], n_ticks: int, world: World
) -> np.ndarray:
    paths = [Simulation(cfg, scenario, s, world=world).run(n_ticks)["series"]["price"] for s in seeds]
    return np.median(np.log(np.stack(paths)), axis=0)


def rmse(a: np.ndarray, b: np.ndarray) -> float:
    n = min(len(a), len(b))
    return float(np.sqrt(np.mean((a[:n] - b[:n]) ** 2)))


@dataclass
class CalibrationResult:
    space: dict[str, tuple[float, float]]
    trials: list[dict[str, Any]]  # {"trial", "params", "rmse"} in run order
    best: dict[str, float]
    best_rmse: float
    best_path: np.ndarray  # median simulated log price at the best parameters
    observed: np.ndarray
    meta: dict[str, Any] = field(default_factory=dict)

    def sensitivity(self) -> dict[str, float]:
        """Spearman rank correlation between each parameter and the trial RMSE. Near 0 means
        the objective hardly depends on that parameter (a sign it is not identifiable)."""
        out = {}
        errs = np.array([t["rmse"] for t in self.trials])
        for name in self.space:
            vals = np.array([t["params"][name] for t in self.trials])
            out[name] = _spearman(vals, errs)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "space": {k: list(v) for k, v in self.space.items()},
            "trials": self.trials,
            "best": self.best,
            "best_rmse": self.best_rmse,
            "best_path": self.best_path.tolist(),
            "observed": self.observed.tolist(),
            "sensitivity": self.sensitivity(),
            "meta": self.meta,
        }


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3:
        return float("nan")
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    c = np.corrcoef(rx, ry)[0, 1]
    return float(c) if math.isfinite(c) else 0.0


def calibrate(
    observed_log_prices: np.ndarray,
    events: Scenario | None,
    param_space: Mapping[str, tuple[float, float]] | None = None,
    n_trials: int = 40,
    runs_per_trial: int = 4,
    *,
    config: Config | None = None,
    seed: int = 0,
    world: World | None = None,
    on_trial: TrialFn | None = None,
    should_stop: Callable[[], bool] | None = None,
    observed_ticks: Sequence[int] | None = None,
    relative: bool = False,
) -> CalibrationResult:
    """Random search minimising RMSE(median simulated log price, observed log price).

    `observed_log_prices` has one value per tick from tick 0, or one value per entry of
    `observed_ticks` (e.g. daily closes: `day * 96 + 63`). With `relative`, both paths are
    measured from their first value, so an observed series at any price level can be matched.
    `on_trial(i, n_trials, trial)` is called after each trial (the UI plots the log).
    """
    cfg = config or Config()
    space = dict(param_space or DEFAULT_SPACE)
    for name, (lo, hi) in space.items():
        if not lo <= hi:
            raise ValueError(f"empty range for {name}")
        with_params(cfg, {name: lo})  # fails early on unknown names
    observed = np.asarray(observed_log_prices, np.float64)
    ticks = np.arange(len(observed)) if observed_ticks is None else np.asarray(observed_ticks, np.int64)
    if len(ticks) != len(observed) or len(ticks) == 0 or np.any(np.diff(ticks) <= 0):
        raise ValueError("observed_ticks must be increasing and match observed_log_prices")
    n_ticks = int(ticks[-1]) + 1
    if relative:
        observed = observed - observed[0]
    scenario = events or Scenario()
    world = world or World.build(cfg)
    rng = np.random.default_rng([seed, 12])
    seeds = list(range(1, runs_per_trial + 1))
    trials: list[dict[str, Any]] = []
    best: tuple[float, dict[str, float], np.ndarray] | None = None
    for i in range(n_trials):
        if should_stop is not None and should_stop():
            break
        params = {k: float(rng.uniform(lo, hi)) for k, (lo, hi) in space.items()}
        path = median_log_path(with_params(cfg, params), scenario, seeds, n_ticks, world)[ticks]
        if relative:
            path = path - path[0]
        err = rmse(path, observed)
        trial = {"trial": i, "params": params, "rmse": err}
        trials.append(trial)
        if best is None or err < best[0]:
            best = (err, params, path)
        if on_trial is not None:
            on_trial(i, n_trials, trial)
    if best is None:
        raise RuntimeError("no calibration trial finished")
    return CalibrationResult(
        space=space,
        trials=trials,
        best=best[1],
        best_rmse=best[0],
        best_path=best[2],
        observed=observed,
        meta={
            "runs_per_trial": runs_per_trial,
            "n_ticks": n_ticks,
            "observed_ticks": ticks.tolist(),
            "relative": relative,
            "n_agents": cfg.n_agents,
            "seed": seed,
        },
    )


# --------------------------------------------------------------------------- recovery test


def recovery_test(
    true_params: Mapping[str, float] | None = None,
    param_space: Mapping[str, tuple[float, float]] | None = None,
    *,
    n_trials: int = 40,
    runs_per_trial: int = 4,
    n_agents: int = 5_000,
    days: float = 5,
    scenario: Scenario | None = None,
    observed_seed: int = 999,
    observed_runs: int = 1,
    seed: int = 0,
    on_trial: TrialFn | None = None,
) -> dict[str, Any]:
    """Simulate "observed" prices from `true_params` (one path with dynamics seed
    `observed_seed`, or with `observed_runs` > 1 the median log path of that many seeds, a
    noise-free target), calibrate on them, and report true vs recovered for each parameter.

    A parameter counts as *recovered* when the error is under 15% of its search range, and as
    *weakly identified* when the objective's rank correlation with it is under 0.2 in size.
    """
    from .scenarios import demo

    space = dict(param_space or DEFAULT_SPACE)
    truth = dict(true_params or {k: (lo + hi) / 2 for k, (lo, hi) in space.items()})
    cfg = replace(Config(), n_agents=n_agents)
    scenario = scenario or demo()
    world = World.build(cfg)
    n_ticks = round(days * TICKS_PER_DAY)
    obs_seeds = list(range(observed_seed, observed_seed + observed_runs))
    observed = median_log_path(with_params(cfg, truth), scenario, obs_seeds, n_ticks, world)
    cal = calibrate(
        observed,
        scenario,
        space,
        n_trials,
        runs_per_trial,
        config=cfg,
        seed=seed,
        world=world,
        on_trial=on_trial,
    )
    truth_path = median_log_path(
        with_params(cfg, truth), scenario, list(range(1, runs_per_trial + 1)), n_ticks, world
    )
    sens = cal.sensitivity()
    rows = []
    for name, (lo, hi) in space.items():
        err = cal.best[name] - truth[name]
        width = hi - lo
        rows.append(
            {
                "parameter": name,
                "true": truth[name],
                "recovered": cal.best[name],
                "error": err,
                "error_share_of_range": abs(err) / width if width > 0 else 0.0,
                "recovered_ok": abs(err) <= 0.15 * width,
                "sensitivity": sens[name],
                "weakly_identified": abs(sens[name]) < 0.2,
            }
        )
    return {
        "rows": rows,
        "best_rmse": cal.best_rmse,
        "rmse_at_truth": rmse(truth_path, observed),  # the floor: noise of one observed path
        "n_trials": len(cal.trials),
        "observed_runs": observed_runs,
        "runs_per_trial": runs_per_trial,
        "n_agents": n_agents,
        "days": days,
        "calibration": cal.to_dict(),
    }


def format_recovery(report: Mapping[str, Any]) -> str:
    lines = [
        "| parameter | true | recovered | error (% of range) | rank corr. with RMSE | verdict |",
        "|---|---|---|---|---|---|",
    ]
    for r in report["rows"]:
        verdict = "recovered" if r["recovered_ok"] else "not recovered"
        if r["weakly_identified"]:
            verdict += ", weakly identified"
        lines.append(
            f"| `{r['parameter']}` | {r['true']:.3g} | {r['recovered']:.3g} | "
            f"{100 * r['error_share_of_range']:.0f}% | {r['sensitivity']:+.2f} | {verdict} |"
        )
    lines.append("")
    lines.append(
        f"Best RMSE {report['best_rmse']:.4f} (log price) vs {report['rmse_at_truth']:.4f} at the true "
        f"parameters; {report['n_trials']} trials × {report['runs_per_trial']} runs, "
        f"{report['n_agents']} agents, {report['days']:g} days, observed = "
        + ("one path." if report["observed_runs"] == 1 else f"median of {report['observed_runs']} paths.")
    )
    return "\n".join(lines)


def main() -> None:  # python -m marketsim.calibration
    import json
    import sys

    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    report = recovery_test(
        observed_runs=runs,
        on_trial=lambda i, n, t: print(f"\r  trial {i + 1}/{n}", end="", file=sys.stderr),
    )
    print(file=sys.stderr)
    print(format_recovery(report))
    print(json.dumps({k: v for k, v in report.items() if k != "calibration"}, indent=1))


if __name__ == "__main__":
    main()
