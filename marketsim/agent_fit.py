"""Fit the agents' behaviour to a real stock's statistical fingerprint (method of simulated moments).

    uv run python -m marketsim.agent_fit AAPL

What is fitted: the behavioural and market-participant parameters the simulation reads at run
time (how strongly sentiment moves orders, strategy switching, risk aversion, how much capital
the prop firms and funds have and how hard they chase momentum / value, how readily agents share
news, unmodelled order flow). What is *not* fitted: the population itself (wealth, archetype
mix, demographics) and the social graph. A price series cannot identify those; they need survey
and platform data (DATA_SOURCES.md).

How: pick `windows` quarter-long stretches (63 trading days) of the training years. Replay each
in the simulation with that stretch's real filings and their *true* reactions (training data, so
this is allowed), and compare the simulated daily returns and volumes with the real ones on six
moments:

* daily return sd, excess kurtosis (fat tails), lag-1 autocorrelation of returns;
* mean autocorrelation of |r| at lags 1-5 (volatility clustering);
* mean |r| on earnings reaction days / on other days (how big events are);
* correlation of daily volume with |r| (the volume-volatility link).

The distance is a sum of squared, scaled moment gaps. A random search (Latin hypercube) over the
parameter box, then the best few are re-run with fresh seeds and the lowest mean distance wins.
Only data before the experiment's split date is used. Writes `docs/experiments/<T>/agent_fit.json`,
which `marketsim.experiment` then applies to every simulation.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from .calibration import with_params
from .config import TICKS_PER_DAY, Config
from .experiment import _WORLD, CLOSE_TICK, Experiment, ExperimentConfig, OriginTask, _init_worker, _scenario
from .sim import Simulation, json_safe

ROOT = Path(__file__).resolve().parents[1]
WINDOW_DAYS = 63

# parameter -> (low, high); every one is read by the simulation at run time
# market.noise_frac and market.prop_momentum_k are fitted to 15-minute bars by marketsim.intraday_fit
SPACE: dict[str, tuple[float, float]] = {
    "trading.sentiment_scale": (0.01, 0.15),
    "trading.switching": (0.05, 0.8),
    "trading.risk_aversion": (0.5, 6.0),
    "market.firm_capital_share": (0.02, 0.4),
    "market.fund_value_k": (1.0, 15.0),
    "diffusion.base_share": (0.05, 0.5),
}
MOMENTS = ("sd", "kurtosis", "acf1", "acf_abs", "earnings_ratio", "volume_corr")
# a gap of one `scale` costs 1: roughly the sampling error of each moment over ~500 days
SCALE = {
    "sd": 0.15,
    "kurtosis": 2.0,
    "acf1": 0.05,
    "acf_abs": 0.05,
    "earnings_ratio": 0.3,
    "volume_corr": 0.1,
}


def _acf(x: np.ndarray, lag: int) -> float:
    x = x - x.mean()
    d = float(np.dot(x, x))
    return float(np.dot(x[:-lag], x[lag:]) / d) if d > 0 and len(x) > lag else 0.0


def moments(windows: list[tuple[np.ndarray, np.ndarray, np.ndarray]]) -> dict[str, float]:
    """Moments pooled over windows of (daily log returns, daily volumes, earnings-day mask)."""
    r = np.concatenate([w[0] for w in windows])
    earn = np.concatenate([w[2] for w in windows])
    z = (r - r.mean()) / (r.std() + 1e-12)
    abs_acf = np.mean([np.mean([_acf(np.abs(w[0]), k) for k in range(1, 6)]) for w in windows])
    vc = [
        float(np.corrcoef(w[1], np.abs(w[0]))[0, 1])
        for w in windows
        if w[1].std() > 0 and np.abs(w[0]).std() > 0
    ]
    a = np.abs(r)
    return {
        "sd": float(r.std(ddof=1)),
        "kurtosis": float(np.mean(z**4) - 3.0),
        "acf1": float(np.mean([_acf(w[0], 1) for w in windows])),
        "acf_abs": float(abs_acf),
        "earnings_ratio": float(a[earn].mean() / a[~earn].mean()) if earn.any() and (~earn).any() else 1.0,
        "volume_corr": float(np.mean(vc)) if vc else 0.0,
    }


def distance(sim: dict[str, float], real: dict[str, float]) -> float:
    gaps = {
        "sd": math.log(max(sim["sd"], 1e-6) / real["sd"]),
        "earnings_ratio": math.log(max(sim["earnings_ratio"], 1e-3) / real["earnings_ratio"]),
    }
    return float(sum(((gaps.get(k, sim[k] - real[k])) / SCALE[k]) ** 2 for k in MOMENTS))


def _simulate_window(task: OriginTask) -> tuple[np.ndarray, np.ndarray]:
    """Daily log returns and daily volumes of one replayed window (first seed only)."""
    cfg = with_params(_WORLD["cfg"], task.params)
    cfg = replace(cfg, market=replace(cfg.market, implied_vol=float(np.clip(task.iv, 0.05, 3.0))))
    days = task.origin - task.start + task.horizon + 1
    out = Simulation(cfg, _scenario(task.events[0]), task.seeds[0], world=_WORLD["world"]).run(
        (days - 1) * TICKS_PER_DAY + CLOSE_TICK + 1
    )["series"]
    p, v = np.asarray(out["price"]), np.asarray(out["volume"])
    closes = p[[d * TICKS_PER_DAY + CLOSE_TICK for d in range(days)]]
    vol = np.array([v[d * TICKS_PER_DAY : (d + 1) * TICKS_PER_DAY].sum() for d in range(days)])
    return np.diff(np.log(closes)), vol[1:]


class AgentFit:
    def __init__(self, exp: Experiment, windows: int = 8, seed: int = 0) -> None:
        self.exp = exp
        h = exp.ds.history
        rng = np.random.default_rng([seed, 23])
        lo, hi = exp.from_idx, exp.split_idx - WINDOW_DAYS - 1
        starts = np.sort(rng.choice(np.arange(lo, hi), size=windows, replace=False))
        self.starts = [int(s) for s in starts]
        earn = {e.reaction_idx for e in exp.ds.events if e.group == "earnings"}
        self.masks = [np.array([s + d in earn for d in range(1, WINDOW_DAYS)]) for s in self.starts]
        self.real = moments(
            [
                (np.diff(np.log(h.close[s : s + WINDOW_DAYS])), h.volume[s + 1 : s + WINDOW_DAYS], m)
                for s, m in zip(self.starts, self.masks, strict=True)
            ]
        )

    def tasks(self, params: dict[str, float], seed: int) -> list[OriginTask]:
        out = []
        for s in self.starts:
            lb = self.exp.cfg.lookback_days
            t = self.exp.task(s + lb, WINDOW_DAYS - 1 - lb, params, oracle=True)
            # start the replay at s exactly (the task starts lookback days before the origin)
            assert t.start == s
            out.append(
                replace(
                    t,
                    iv=self.exp.trailing_vol(s) * math.sqrt(252),
                    seeds=[seed * 7919 + s],
                    events=t.events[:1],
                )
            )
        return out

    def evaluate(
        self, ex: ProcessPoolExecutor, cands: list[dict[str, float]], seed: int
    ) -> list[dict[str, Any]]:
        tasks = [t for p in cands for t in self.tasks(p, seed)]
        res = list(ex.map(_simulate_window, tasks, chunksize=2))
        k = len(self.starts)
        out = []
        for i, p in enumerate(cands):
            m = moments(
                [(r, v, mask) for (r, v), mask in zip(res[i * k : (i + 1) * k], self.masks, strict=True)]
            )
            out.append({"params": p, "moments": m, "distance": distance(m, self.real)})
        return out


def latin_hypercube(n: int, rng: np.random.Generator) -> list[dict[str, float]]:
    keys = list(SPACE)
    u = (np.argsort(rng.random((n, len(keys))), axis=0) + rng.random((n, len(keys)))) / n
    return [
        {k: float(SPACE[k][0] + u[i, j] * (SPACE[k][1] - SPACE[k][0])) for j, k in enumerate(keys)}
        for i in range(n)
    ]


def defaults() -> dict[str, float]:
    cfg = Config()
    return {k: float(getattr(getattr(cfg, k.split(".")[0]), k.split(".")[1])) for k in SPACE}


def fit(
    ticker: str = "AAPL",
    candidates: int = 48,
    windows: int = 8,
    finalists: int = 4,
    extra_seeds: int = 2,
    n_agents: int = 1000,
    workers: int = 10,
    split: str = "2024-01-01",
) -> dict[str, Any]:
    t0 = time.perf_counter()
    exp = Experiment(
        ExperimentConfig(ticker=ticker, split=split, n_agents=n_agents, workers=workers, agent_params={})
    )
    af = AgentFit(exp, windows)
    print(f"real moments ({len(af.starts)} windows of {WINDOW_DAYS} days, before {split}): {af.real}")
    rng = np.random.default_rng(5)
    cands = [defaults(), *latin_hypercube(candidates, rng)]
    with ProcessPoolExecutor(workers, initializer=_init_worker, initargs=(n_agents, 0)) as ex:
        first = af.evaluate(ex, cands, seed=1)
        for i, r in enumerate(first):
            r["candidate"] = i
        ranked = sorted(first, key=lambda r: r["distance"])
        print("defaults distance:", round(first[0]["distance"], 2), "best:", round(ranked[0]["distance"], 2))
        final = []
        for r in ranked[:finalists]:
            reps = [r] + [af.evaluate(ex, [r["params"]], seed=s)[0] for s in range(2, 2 + extra_seeds)]
            mean_m = {k: float(np.mean([x["moments"][k] for x in reps])) for k in MOMENTS}
            final.append(
                {
                    "params": r["params"],
                    "candidate": r["candidate"],
                    "distance": float(np.mean([x["distance"] for x in reps])),
                    "moments": mean_m,
                }
            )
            print(f"  finalist {r['candidate']}: mean distance {final[-1]['distance']:.2f}")
        base_reps = [first[0]] + [
            af.evaluate(ex, [first[0]["params"]], seed=s)[0] for s in range(2, 2 + extra_seeds)
        ]
    best = min(final, key=lambda r: r["distance"])
    base = {
        "params": first[0]["params"],
        "distance": float(np.mean([x["distance"] for x in base_reps])),
        "moments": {k: float(np.mean([x["moments"][k] for x in base_reps])) for k in MOMENTS},
    }
    # identification: rank correlation of each parameter with the distance over the search
    dist = np.array([r["distance"] for r in first])
    ident = {}
    for k in SPACE:
        x = np.array([r["params"][k] for r in first])
        rx, rd = np.argsort(np.argsort(x)), np.argsort(np.argsort(dist))
        ident[k] = float(np.corrcoef(rx, rd)[0, 1])
    return json_safe(
        {
            "ticker": ticker,
            "split": split,
            "windows": [exp.ds.history.dates[s] for s in af.starts],
            "window_days": WINDOW_DAYS,
            "real_moments": af.real,
            "scale": SCALE,
            "space": {k: list(v) for k, v in SPACE.items()},
            "defaults": base,
            "best": best,
            "finalists": final,
            "search": first,
            "identification": ident,
            "seconds": time.perf_counter() - t0,
        }
    )


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Fit agent behaviour to a stock's stylised facts.")
    ap.add_argument("ticker", nargs="?", default="AAPL")
    ap.add_argument("--candidates", type=int, default=48)
    ap.add_argument("--windows", type=int, default=8)
    ap.add_argument("--agents", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=min(10, max(1, (os.cpu_count() or 2) - 2)))
    args = ap.parse_args(argv)
    res = fit(args.ticker, args.candidates, args.windows, n_agents=args.agents, workers=args.workers)
    out = ROOT / "docs" / "experiments" / args.ticker.upper()
    out.mkdir(parents=True, exist_ok=True)
    (out / "agent_fit.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"best distance {res['best']['distance']:.2f} (defaults {res['defaults']['distance']:.2f})")
    print("best params:", res["best"]["params"])
    print(f"wrote {out / 'agent_fit.json'} in {res['seconds']:.0f}s")


if __name__ == "__main__":
    main()
