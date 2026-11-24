"""Fit the market's tick dynamics to a real stock's 15-minute bars.

    uv run python scripts/fetch_market_data.py AAPL --intraday     # last 60 days of 15-min bars
    uv run python -m marketsim.intraday_fit AAPL --agents 100000

One simulation tick is 15 minutes, so the simulated open-market ticks and real 15-minute bars
are directly comparable. Moments (regular hours only, overnight gaps excluded):

* lag-1 autocorrelation of 15-min returns (real prices are close to a martingale; agents who
  hear news over hours make the simulated flow persistent);
* lag-1 autocorrelation of |15-min returns| (volatility clustering, incl. the intraday U-shape);
* excess kurtosis (fat tails);
* 15-min return sd relative to the daily sd (how volatility is spread over the day).

Fitted: `market.mm_flow_anticipation` (fast traders pricing in predictable flow),
`market.noise_vol_feedback` (unmodelled flow that grows with recent volatility) and
`market.noise_frac`. The scenario is a quiet market (no scripted events), so the fit is about the
market's own dynamics; events add their jumps on top. Writes
`docs/experiments/<T>/intraday_fit.json`.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from .calibration import with_params
from .config import TICKS_PER_DAY, Config
from .events import hawkes_events
from .market import is_market_open
from .sim import Scenario, Simulation, World, json_safe

ROOT = Path(__file__).resolve().parents[1]
SPACE = {
    "market.impact_Y": (0.05, 1.0),  # how far the agents' own flow moves the price (depth)
    "market.noise_frac": (0.3, 1.5),  # unmodelled liquidity flow
    "market.noise_vol_feedback": (0.0, 1.0),
    "market.prop_momentum_k": (0.0, 80.0),
    "market.mm_flow_anticipation": (0.0, 0.6),
    "market.noise_permanence": (0.0, 1.0),
    # background news (self-exciting synthetic events, `events.hawkes_events`): real days differ
    # because of news, which is where most fat tails and volatility clustering come from
    "news.rate_per_tick": (0.0, 0.08),
    "news.impact_sd": (0.001, 0.015),
}
NEWS_ALPHA, NEWS_BETA = 0.3, 0.5  # self-excitation: branching ratio ~0.47
# fitted background news for AAPL (refine): ~2.9 synthetic news items per 96-tick day, impact sd 0.54%
BACKGROUND_NEWS = {"news.rate_per_tick": 0.0297, "news.impact_sd": 0.00538}
# intraday_share is reported, not fitted: the simulation has no overnight news, while ~25% of real
# daily variance happens overnight
SCALE = {"acf1": 0.03, "acf_abs1": 0.05, "kurtosis": 1.5, "log_sd": 0.15, "vr_day": 0.15}


def _acf(x: np.ndarray, lag: int = 1) -> float:
    x = x - x.mean()
    d = float(np.dot(x, x))
    return float(np.dot(x[:-lag], x[lag:]) / d) if d > 0 and len(x) > lag + 2 else 0.0


def moments(days: list[np.ndarray], daily: np.ndarray) -> dict[str, float]:
    """`days`: each day's 15-min log returns (regular hours); `daily`: close-to-close returns."""
    r = np.concatenate(days)
    z = (r - r.mean()) / (r.std() + 1e-15)
    return {
        "acf1": float(np.mean([_acf(d) for d in days if len(d) > 4])),
        "acf_abs1": _acf(np.abs(r)),
        "kurtosis": float(np.mean(z**4) - 3.0),
        # sd of a 15-min return x sqrt(bars per day) / daily sd: 1 if intraday returns add up
        # like a random walk, > 1 if they mean-revert, < 1 if they trend
        "intraday_share": float(r.std() * math.sqrt(len(r) / max(len(days), 1)) / (daily.std() + 1e-15)),
        "sd_15m": float(r.std()),
        # open-to-close variance / (bars x 15-min variance): 1 for a random walk, < 1 if moves
        # reverse within the day (no overnight news involved, unlike intraday_share)
        "vr_day": float(
            np.var([d.sum() for d in days]) / (np.mean([len(d) for d in days]) * r.var() + 1e-30)
        ),
    }


def distance(sim: dict[str, float], real: dict[str, float]) -> float:
    """Scaled squared gaps; the size of a 15-min move counts too (as a log ratio), or a fit can
    remove the momentum by drowning it in noise."""
    gaps = {k: (sim[k] - real[k]) / SCALE[k] for k in SCALE if k != "log_sd"}
    gaps["log_sd"] = math.log(max(sim["sd_15m"], 1e-12) / real["sd_15m"]) / SCALE["log_sd"]
    return float(sum(g * g for g in gaps.values()))


def real_moments(ticker: str) -> dict[str, Any]:
    path = ROOT / "data" / ticker.upper() / "intraday_15m.csv"
    by_day: dict[str, list[float]] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_day.setdefault(row["time"][:10], []).append(float(row["close"]))
    days = [np.diff(np.log(v)) for _, v in sorted(by_day.items()) if len(v) > 10]
    closes = np.array([v[-1] for _, v in sorted(by_day.items()) if len(v) > 10])
    m = moments(days, np.diff(np.log(closes)))
    m["days"] = len(days)
    return m


def sim_days(series_price: list[float], n_days: int) -> tuple[list[np.ndarray], np.ndarray]:
    p = np.asarray(series_price, np.float64)
    days, closes = [], []
    for d in range(n_days):
        ticks = [
            t for t in range(d * TICKS_PER_DAY, (d + 1) * TICKS_PER_DAY) if is_market_open(t) and t < len(p)
        ]
        if len(ticks) < 10:
            continue
        x = p[ticks]
        days.append(np.diff(np.log(x)))
        closes.append(x[-1])
    return days, np.diff(np.log(np.array(closes)))


_W: dict[str, Any] = {}


def _init(n_agents: int, survey: str) -> None:
    cfg = replace(Config(), n_agents=n_agents, seed=0)
    cfg = replace(cfg, population=replace(cfg.population, survey=survey))
    _W["cfg"], _W["world"] = cfg, World.build(cfg)


def background_news(params: dict[str, float], n_ticks: int, seed: int) -> Scenario:
    rate = params.get("news.rate_per_tick", 0.0)
    if rate <= 0:
        return Scenario()
    rng = np.random.default_rng([seed, 99])
    return Scenario(
        hawkes_events(
            rate, NEWS_ALPHA, NEWS_BETA, n_ticks, rng, impact_sd=params.get("news.impact_sd", 0.005)
        )
    )


def _run(args: tuple[dict[str, float], int, int, float]) -> tuple[list[np.ndarray], np.ndarray]:
    params, seed, n_days, iv = args
    cfg = with_params(_W["cfg"], {k: v for k, v in params.items() if not k.startswith("news.")})
    cfg = replace(cfg, market=replace(cfg.market, implied_vol=iv))
    sc = background_news(params, n_days * TICKS_PER_DAY, seed)
    p = Simulation(cfg, sc, seed, world=_W["world"]).run(n_days * TICKS_PER_DAY)["series"]["price"]
    return sim_days(p, n_days)


def evaluate(
    ex: ProcessPoolExecutor, cands: list[dict[str, float]], seeds: list[int], n_days: int, iv: float
) -> list[dict[str, float]]:
    jobs = [(c, s, n_days, iv) for c in cands for s in seeds]
    res = list(ex.map(_run, jobs))
    out = []
    for i, _ in enumerate(cands):
        days: list[np.ndarray] = []
        daily: list[np.ndarray] = []
        for d, r in res[i * len(seeds) : (i + 1) * len(seeds)]:
            # drop day 0: the market maker's depth settles over the first day
            days += d[1:]
            daily.append(r[1:])
        out.append(moments(days, np.concatenate(daily)))
    return out


def fit(
    ticker: str = "AAPL",
    n_agents: int = 100_000,
    candidates: int = 40,
    seeds: int = 2,
    n_days: int = 6,
    workers: int = 8,
    survey: str = "us",
) -> dict[str, Any]:
    t0 = time.perf_counter()
    real = real_moments(ticker)
    daily_sd = real["sd_15m"] * math.sqrt(26) / max(real["intraday_share"], 1e-9)
    iv = float(daily_sd * math.sqrt(252))
    print(f"real 15-min moments ({real['days']} days): {real}")
    rng = np.random.default_rng(11)
    keys = list(SPACE)
    u = (
        np.argsort(rng.random((candidates, len(keys))), axis=0) + rng.random((candidates, len(keys)))
    ) / candidates
    cfg0 = Config()
    base = {
        k: float(getattr(getattr(cfg0, k.split(".")[0]), k.split(".")[1]))
        if not k.startswith("news.")
        else 0.0
        for k in keys
    }
    cands = [base] + [
        {k: SPACE[k][0] + u[i, j] * (SPACE[k][1] - SPACE[k][0]) for j, k in enumerate(keys)}
        for i in range(candidates)
    ]
    with ProcessPoolExecutor(workers, initializer=_init, initargs=(n_agents, survey)) as ex:
        ms = evaluate(ex, cands, list(range(1, seeds + 1)), n_days, iv)
        rows = [
            {"params": c, "moments": m, "distance": distance(m, real)} for c, m in zip(cands, ms, strict=True)
        ]
        top = sorted(rows[1:], key=lambda r: r["distance"])[:4]
        fresh = list(range(10, 10 + seeds))
        recheck = evaluate(ex, [r["params"] for r in top], fresh, n_days, iv)
        for r, m in zip(top, recheck, strict=True):
            r["recheck_distance"] = distance(m, real)
            r["recheck_moments"] = m
    best = min(top, key=lambda r: (r["distance"] + r["recheck_distance"]) / 2)
    print(f"defaults: {rows[0]['moments']}  distance {rows[0]['distance']:.1f}")
    print(f"best: {best['params']}  distance {best['distance']:.1f} / recheck {best['recheck_distance']:.1f}")
    print(f"best moments: {best['recheck_moments']}")
    return json_safe(
        {
            "ticker": ticker.upper(),
            "n_agents": n_agents,
            "survey": survey,
            "days_per_run": n_days,
            "seeds": seeds,
            "implied_vol": iv,
            "real": real,
            "defaults": rows[0],
            "best": best,
            "search": rows,
            "seconds": time.perf_counter() - t0,
        }
    )


def refine(
    ticker: str = "AAPL",
    n_agents: int = 100_000,
    top: int = 3,
    variants: int = 4,
    seeds: int = 4,
    n_days: int = 10,
    workers: int = 8,
) -> dict[str, Any]:
    """Re-score the search's best candidates and small perturbations of them on fresh seeds and
    longer runs (the first pass is noisy once news adds fat tails), and choose the lowest mean."""
    path = ROOT / "docs" / "experiments" / ticker.upper() / "intraday_fit.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    real, iv = doc["real"], doc["implied_vol"]
    rng = np.random.default_rng(23)
    best = sorted(doc["search"], key=lambda r: r["distance"])[:top]
    cands: list[dict[str, float]] = []
    for r in best:
        cands.append(dict(r["params"]))
        for _ in range(variants):
            cands.append(
                {
                    k: float(np.clip(v * math.exp(rng.normal(0, 0.25)), *SPACE[k])) if k in SPACE else v
                    for k, v in r["params"].items()
                }
            )
    with ProcessPoolExecutor(workers, initializer=_init, initargs=(n_agents, doc.get("survey", "us"))) as ex:
        ms = evaluate(ex, cands, list(range(20, 20 + seeds)), n_days, iv)
    rows: list[dict[str, Any]] = [
        {"params": c, "moments": m, "distance": distance(m, real)} for c, m in zip(cands, ms, strict=True)
    ]
    chosen = min(rows, key=lambda r: float(r["distance"]))
    doc["refined"] = {"seeds": seeds, "days_per_run": n_days, "rows": rows, "chosen": chosen}
    path.write_text(json.dumps(json_safe(doc), indent=1), encoding="utf-8")
    print(f"chosen: {chosen['params']}  distance {chosen['distance']:.1f}")
    print(f"moments: {chosen['moments']}")
    return doc


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Fit tick dynamics to real 15-minute bars.")
    ap.add_argument("ticker", nargs="?", default="AAPL")
    ap.add_argument("--agents", type=int, default=100_000)
    ap.add_argument("--candidates", type=int, default=40)
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--days", type=int, default=6)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--refine", action="store_true", help="re-score the best candidates (after a fit)")
    args = ap.parse_args(argv)
    if args.refine:
        refine(args.ticker, args.agents, workers=args.workers)
        return
    res = fit(args.ticker, args.agents, args.candidates, args.seeds, args.days, args.workers)
    out = ROOT / "docs" / "experiments" / args.ticker.upper() / "intraday_fit.json"
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"wrote {out} in {res['seconds']:.0f}s")


if __name__ == "__main__":
    main()
