"""Train on a real stock's past events, then forecast its later prices out of sample.

    uv run python -m marketsim.experiment AAPL --split 2024-01-01

1. **Events:** every SEC filing of the company becomes an event (`realdata`), labelled with its
   actual abnormal return on the reaction day (event study against SPY).
2. **Impact model (classification + size):** trained on events before `--split` only
   (`impact_model`), with its regularisation chosen on the last 30% of the training events.
3. **Simulation training:** a small grid over the simulator's market parameters, scored by the
   mean CRPS of one-day-ahead forecasts on training-period origins.
4. **Out-of-sample backtest:** for every trading day after the split, forecast the close
   `horizon` days ahead with four models and score them with CRPS against what happened:

   * ``random_walk``: lognormal, trailing 20-day volatility (the benchmark);
   * ``event_random_walk``: the same plus a jump for every *scheduled* earnings release in the
     horizon, drawn from the impact model (earnings dates are announced weeks ahead);
   * ``abm``: the agent-based simulation, seeded with the events known at the forecast origin
     (as the impact model reads them) plus scheduled earnings in the horizon (a fresh draw
     from the impact model in each run);
   * ``abm_oracle``: the simulation told every event in the window *and its true reaction*.
     It uses the future and is not a forecast; it shows how much better perfect event
     knowledge would make the simulation.

5. **Report:** `docs/experiments/<TICKER>/` gets results.json, report.md and plots, and
   `data/<TICKER>/events.json` gets the labelled events in the format the web app uploads.

No step reads anything after a forecast origin except the oracle and the scoring.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from .backtest import crps_sample
from .calibration import with_params
from .config import TICKS_PER_DAY, Config
from .events import Event
from .impact_model import ImpactModel
from .realdata import FEATURES, Dataset, RealEvent, feature_matrix, features_at, load_dataset
from .sim import Scenario, Simulation, World, json_safe

ROOT = Path(__file__).resolve().parents[1]
CLOSE_TICK = 63
MODELS = ("random_walk", "event_random_walk", "abm", "abm_oracle")
KIND = {
    "earnings": "earnings",
    "periodic_report": "regulatory",
    "executive": "statement",
    "vote": "statement",
    "governance": "statement",
    "other_event": "statement",
    "disclosure": "statement",
    "agreement": "product",
}


@dataclass
class ExperimentConfig:
    ticker: str = "AAPL"
    split: str = "2024-01-01"  # train on events / origins before, test after
    train_from: str = "2016-01-01"
    horizons: tuple[int, ...] = (1, 5)
    n_agents: int = 1500
    runs: int = 16  # simulation runs per origin
    rw_samples: int = 4000
    lookback_days: int = 5  # the market maker's depth settles over the first day
    vol_window: int = 20
    train_origins: int = 200
    test_every: int = 1  # forecast from every n-th trading day of the test period
    grid: dict[str, list[float]] = field(
        default_factory=lambda: {
            # the agents' own order flow is too smooth (thousands of independent choices average
            # out), so the unmodelled-flow noise is the main lever on the forecast spread
            "market.noise_frac": [0.6, 1.0, 1.5, 2.2],
            "market.impact_Y": [0.5, 0.9],
            "market.mm_news_pass_through": [0.6, 1.0],
        }
    )
    workers: int = min(8, max(1, (os.cpu_count() or 2) - 2))  # each worker holds a population
    seed: int = 0
    data_root: str | None = None
    out_dir: str | None = None


# --------------------------------------------------------------------------- events -> simulation


def release_slot(ds: Dataset, e: RealEvent) -> tuple[int, int]:
    """(trading-day index, tick within that day) at which the release enters the simulation."""
    t = datetime.fromisoformat(e.released)
    day = t.date().isoformat()
    idx = ds.history.index_on_or_after(day)
    if idx < len(ds.history.dates) and ds.history.dates[idx] == day:
        return idx, (t.hour * 60 + t.minute) // 15
    return idx, 32  # weekend / holiday release: 08:00 on the next trading day


def to_event(e: RealEvent, tick: int, impact: float, sentiment: float, size: float, eid: int) -> Event:
    return Event(
        tick=tick,
        kind=KIND[e.group],
        ticker=0,
        true_impact=float(np.clip(impact, -0.5, 0.5)),
        sentiment=float(np.clip(sentiment, -1.0, 1.0)),
        credibility=0.95,
        salience=float(np.clip(0.3 + 8.0 * size, 0.2, 1.0)),
        complexity=0.4 if e.group in ("earnings", "periodic_report") else 0.2,
        seeding="official",
        id=eid,
    )


@dataclass
class OriginTask:
    origin: int
    horizon: int
    start: int
    iv: float
    params: dict[str, float]
    seeds: list[int]
    # per-run event lists: [(tick, kind, impact, sentiment, salience, complexity)]
    events: list[list[tuple[int, str, float, float, float, float]]]


def _scenario(rows: list[tuple[int, str, float, float, float, float]]) -> Scenario:
    evs = [
        Event(t, k, 0, imp, sent, 0.95, sal, cx, "official", id=i)
        for i, (t, k, imp, sent, sal, cx) in enumerate(sorted(rows))
    ]
    return Scenario(evs)


_WORLD: dict[str, Any] = {}


def _init_worker(n_agents: int, seed: int) -> None:
    cfg = replace(Config(), n_agents=n_agents, seed=seed)
    _WORLD["cfg"], _WORLD["world"] = cfg, World.build(cfg)


def _simulate(task: OriginTask) -> np.ndarray:
    """Simulated ratio close[origin + horizon] / close[origin], one per run."""
    base: Config = _WORLD["cfg"]
    cfg = with_params(base, task.params)
    cfg = replace(cfg, market=replace(cfg.market, implied_vol=float(np.clip(task.iv, 0.05, 3.0))))
    o_tick = (task.origin - task.start) * TICKS_PER_DAY + CLOSE_TICK
    end_tick = o_tick + task.horizon * TICKS_PER_DAY
    out = []
    for seed, rows in zip(task.seeds, task.events, strict=True):
        p = Simulation(cfg, _scenario(rows), seed, world=_WORLD["world"]).run(end_tick + 1)["series"]["price"]
        out.append(p[end_tick] / p[o_tick])
    return np.asarray(out)


# --------------------------------------------------------------------------- the experiment


class Experiment:
    def __init__(self, cfg: ExperimentConfig) -> None:
        self.cfg = cfg
        root = Path(cfg.data_root) if cfg.data_root else None
        self.ds = load_dataset(cfg.ticker, root)
        h = self.ds.history
        self.split_idx = h.index_on_or_after(cfg.split)
        self.from_idx = max(h.index_on_or_after(cfg.train_from), 130)
        earn_days = {e.reaction_idx for e in self.ds.events if e.group == "earnings"}
        # an earnings release owns its reaction day: other filings on that day (e.g. the 10-Q
        # filed the next morning) are kept as events but not used as training labels
        self.labelled = [
            e
            for e in self.ds.events
            if e.label is not None and not (e.group != "earnings" and e.reaction_idx in earn_days)
        ]
        self.train_events = [e for e in self.labelled if e.reaction_idx < self.split_idx]
        self.test_events = [e for e in self.labelled if e.reaction_idx >= self.split_idx]
        self.slots = {e.id: release_slot(self.ds, e) for e in self.ds.events}
        self.rng = np.random.default_rng([cfg.seed, 42])
        self.model = self._fit_impact_model()

    # ---------------------------------------------------------------- impact model
    def _fit_impact_model(self) -> ImpactModel:
        tr = self.train_events
        X, y = feature_matrix(tr), np.array([e.label for e in tr])
        cut = int(len(tr) * 0.7)  # time-ordered validation split inside the training years
        best = None
        for l2 in (0.3, 1.0, 3.0, 10.0, 30.0, 100.0):
            m = ImpactModel(l2=l2).fit(X[:cut], y[:cut])
            ll = m.evaluate(X[cut:], y[cut:], y[:cut])["log_loss"]
            if best is None or ll < best[0]:
                best = (ll, l2)
        assert best is not None
        self.l2 = best[1]
        return ImpactModel(l2=self.l2).fit(X, y)

    def impact_report(self) -> dict[str, Any]:
        tr, te = self.train_events, self.test_events
        ytr = np.array([e.label for e in tr])
        res: dict[str, Any] = {
            "l2": self.l2,
            "n_train": len(tr),
            "n_test": len(te),
            "test": self.model.evaluate(feature_matrix(te), np.array([e.label for e in te]), ytr),
        }
        earn = [e for e in te if e.group == "earnings"]
        if earn:
            res["test_earnings"] = self.model.evaluate(
                feature_matrix(earn), np.array([e.label for e in earn]), ytr
            )
        # standardised coefficients: which features push towards "up" and towards bigger moves
        res["direction_weights"] = {
            k: float(self.model.W[i, 2] - self.model.W[i, 0]) for i, k in enumerate(FEATURES)
        }
        res["size_weights"] = {k: float(self.model.size_w[i]) for i, k in enumerate(FEATURES)}
        return res

    # ---------------------------------------------------------------- per-origin inputs
    def trailing_vol(self, o: int) -> float:
        c = self.ds.history.close
        r = np.diff(np.log(c[max(0, o - self.cfg.vol_window) : o + 1]))
        return float(r.std(ddof=1)) if len(r) > 2 else 0.015

    def scheduled_in_horizon(self, o: int, h: int) -> list[RealEvent]:
        return [e for e in self.ds.events if e.group == "earnings" and o < e.reaction_idx <= o + h]

    def _masked_features(self, e: RealEvent, o: int) -> np.ndarray:
        """What is known at origin `o` about a scheduled release: its group and the market
        features up to o, not its numbers."""
        f = dict(e.features)
        f.update(features_at(self.ds.history, o + 1))
        f["eps_yoy"] = f["rev_yoy"] = 0.0
        return np.array([[f[k] for k in FEATURES]])

    def task(self, o: int, h: int, params: dict[str, float], oracle: bool) -> OriginTask:
        start = max(0, o - self.cfg.lookback_days)
        runs = self.cfg.runs
        rows: list[list[tuple[int, str, float, float, float, float]]] = [[] for _ in range(runs)]

        def tick_of(e: RealEvent) -> int | None:
            idx, t = self.slots[e.id]
            if idx < start:
                return None
            return (idx - start) * TICKS_PER_DAY + t

        window = [e for e in self.ds.events if start <= e.reaction_idx <= o + h]
        for e in window:
            tk = tick_of(e)
            if tk is None:
                continue
            cx = 0.4 if e.group in ("earnings", "periodic_report") else 0.2
            if oracle:
                lab = e.label if e.label is not None else 0.0
                sal = float(np.clip(0.3 + 8.0 * abs(lab), 0.2, 1.0))
                for r in rows:
                    r.append((tk, KIND[e.group], lab, float(np.clip(20 * lab, -1, 1)), sal, cx))
            elif e.reaction_idx <= o:  # already released: the model's reading of it
                X = feature_matrix([e])
                imp = float(self.model.expected(X)[0])
                p = self.model.proba(X)[0]
                sal = float(np.clip(0.3 + 8.0 * self.model.size(X)[0], 0.2, 1.0))
                for r in rows:
                    r.append((tk, KIND[e.group], imp, float(p[2] - p[0]), sal, cx))
            elif e.group == "earnings":  # scheduled: a fresh draw of its reaction in every run
                X = self._masked_features(e, o)
                draws = self.model.sample(X, self.rng, runs)[:, 0]
                sal = float(np.clip(0.3 + 8.0 * self.model.size(X)[0], 0.2, 1.0))
                for r, d in zip(rows, draws, strict=True):
                    r.append((tk, KIND[e.group], float(d), float(np.clip(20 * d, -1, 1)), sal, cx))
        return OriginTask(
            origin=o,
            horizon=h,
            start=start,
            iv=self.trailing_vol(o) * math.sqrt(252),
            params=params,
            seeds=[self.cfg.seed * 100_003 + o * 101 + i for i in range(runs)],
            events=rows,
        )

    def random_walks(self, o: int, h: int) -> tuple[np.ndarray, np.ndarray]:
        s = self.trailing_vol(o) * math.sqrt(h)
        z = self.rng.normal(-0.5 * s * s, s, self.cfg.rw_samples)
        jumps = np.zeros(self.cfg.rw_samples)
        for e in self.scheduled_in_horizon(o, h):
            jumps += self.model.sample(self._masked_features(e, o), self.rng, self.cfg.rw_samples)[:, 0]
        return np.exp(z), np.exp(z + jumps)

    # ---------------------------------------------------------------- running
    def _run_tasks(self, ex: ProcessPoolExecutor | None, tasks: list[OriginTask]) -> list[np.ndarray]:
        if ex is None:
            if "world" not in _WORLD:
                _init_worker(self.cfg.n_agents, self.cfg.seed)
            return [_simulate(t) for t in tasks]
        return list(ex.map(_simulate, tasks, chunksize=4))

    def train_simulation(
        self, ex: ProcessPoolExecutor | None
    ) -> tuple[dict[str, float], list[dict[str, Any]]]:
        """Grid search over market parameters on training origins, scored by one-day CRPS."""
        h = 1
        # a representative sample of training days (earnings days at their natural rate), so the
        # chosen spread fits ordinary days as well as event days
        cand = np.arange(self.from_idx, self.split_idx - h)
        rng = np.random.default_rng([self.cfg.seed, 7])
        origins = sorted(
            int(o) for o in rng.choice(cand, size=min(self.cfg.train_origins, len(cand)), replace=False)
        )
        keys = list(self.cfg.grid)
        combos = [dict(zip(keys, vals, strict=True)) for vals in _product([self.cfg.grid[k] for k in keys])]
        close = self.ds.history.close
        log: list[dict[str, Any]] = []
        for params in combos:
            t0 = time.perf_counter()
            sims = self._run_tasks(ex, [self.task(o, h, params, oracle=False) for o in origins])
            crps = [
                crps_sample(close[o] * s, close[o + h]) / close[o] for o, s in zip(origins, sims, strict=True)
            ]
            log.append(
                {"params": params, "mean_crps": float(np.mean(crps)), "seconds": time.perf_counter() - t0}
            )
            print(f"  train {params}: CRPS {np.mean(crps) * 100:.4f}% of price")
        best = min(log, key=lambda r: r["mean_crps"])
        return dict(best["params"]), log

    def backtest(
        self, ex: ProcessPoolExecutor | None, params: dict[str, float], h: int
    ) -> list[dict[str, Any]]:
        hist = self.ds.history
        origins = list(range(self.split_idx, len(hist.dates) - h, self.cfg.test_every))
        tasks = [self.task(o, h, params, oracle=False) for o in origins]
        oracle_tasks = [self.task(o, h, params, oracle=True) for o in origins]
        sims = self._run_tasks(ex, tasks + oracle_tasks)
        abm, orc = sims[: len(origins)], sims[len(origins) :]
        rows = []
        for i, o in enumerate(origins):
            p0, actual = float(hist.close[o]), float(hist.close[o + h])
            rw, erw = self.random_walks(o, h)
            row: dict[str, Any] = {
                "origin": hist.dates[o],
                "target": hist.dates[o + h],
                "close": p0,
                "actual": actual,
                "actual_return": actual / p0 - 1.0,
                "earnings_in_horizon": bool(self.scheduled_in_horizon(o, h)),
                "events_known": sum(
                    1 for e in self.ds.events if o - self.cfg.lookback_days <= e.reaction_idx <= o
                ),
            }
            for name, ratios in zip(MODELS, (rw, erw, abm[i], orc[i]), strict=True):
                s = p0 * ratios
                row[name] = {
                    "crps": crps_sample(s, actual) / p0,
                    "median": float(np.median(s)),
                    "q05": float(np.quantile(s, 0.05)),
                    "q95": float(np.quantile(s, 0.95)),
                    "p_up": float((s > p0).mean()),
                }
            rows.append(row)
        return rows

    def run(self) -> dict[str, Any]:
        t0 = time.perf_counter()
        impact = self.impact_report()
        print(f"impact model: l2={self.l2}, test accuracy {impact['test']['accuracy']:.2f}")
        ex = (
            ProcessPoolExecutor(
                self.cfg.workers, initializer=_init_worker, initargs=(self.cfg.n_agents, self.cfg.seed)
            )
            if self.cfg.workers > 1
            else None
        )
        try:
            params, train_log = self.train_simulation(ex)
            print(f"trained simulation parameters: {params}")
            results = {h: self.backtest(ex, params, h) for h in self.cfg.horizons}
        finally:
            if ex is not None:
                ex.shutdown()
        hist = self.ds.history
        return json_safe(
            {
                "ticker": hist.ticker,
                "name": hist.name,
                "config": {**asdict(self.cfg), "horizons": list(self.cfg.horizons)},
                "period": {
                    "train": [hist.dates[self.from_idx], hist.dates[self.split_idx - 1]],
                    "test": [hist.dates[self.split_idx], hist.dates[-1]],
                },
                "events": {
                    "total": len(self.ds.events),
                    "labelled": len(self.labelled),
                    "train": len(self.train_events),
                    "test": len(self.test_events),
                },
                "impact_model": impact,
                "simulation": {"params": params, "grid": train_log},
                "backtest": {
                    str(h): {"summary": summarize(rows), "origins": rows} for h, rows in results.items()
                },
                "seconds": time.perf_counter() - t0,
            }
        )


def _product(lists: Sequence[Sequence[float]]) -> list[tuple[float, ...]]:
    out: list[tuple[float, ...]] = [()]
    for xs in lists:
        out = [(*p, x) for p in out for x in xs]
    return out


# --------------------------------------------------------------------------- scoring


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def stats(sub: list[dict[str, Any]]) -> dict[str, Any]:
        if not sub:
            return {"n": 0}
        rw = np.mean([r["random_walk"]["crps"] for r in sub])
        out: dict[str, Any] = {"n": len(sub)}
        up = np.array([r["actual_return"] > 0 for r in sub])
        for m in MODELS:
            crps = float(np.mean([r[m]["crps"] for r in sub]))
            inside = np.mean([r[m]["q05"] <= r["actual"] <= r[m]["q95"] for r in sub])
            pu = np.array([r[m]["p_up"] for r in sub])
            out[m] = {
                "mean_crps_pct": 100 * crps,
                "skill_vs_random_walk": float(1 - crps / rw) if rw > 0 else 0.0,
                "coverage_90": float(inside),
                "direction_accuracy": float(((pu > 0.5) == up).mean()),
                "brier_up": float(np.mean((pu - up) ** 2)),
            }
        return out

    return {
        "all": stats(rows),
        "earnings_in_horizon": stats([r for r in rows if r["earnings_in_horizon"]]),
        "no_earnings": stats([r for r in rows if not r["earnings_in_horizon"]]),
    }


# --------------------------------------------------------------------------- outputs


def write_events_json(exp: Experiment, path: Path) -> None:
    """Labelled events in the dated format the web app's Analysis page uploads."""
    out = []
    for e in exp.ds.events:
        t = datetime.fromisoformat(e.released)
        lab = e.label or 0.0
        out.append(
            {
                "date": exp.ds.history.dates[min(exp.slots[e.id][0], len(exp.ds.history.dates) - 1)],
                "time": f"{t.hour:02d}:{t.minute:02d}" if exp.slots[e.id][1] != 32 else "08:00",
                "kind": KIND[e.group],
                "true_impact": float(np.clip(lab, -0.5, 0.5)),
                "sentiment": float(np.clip(20 * lab, -1, 1)),
                "credibility": 0.95,
                "salience": float(np.clip(0.3 + 8 * abs(lab), 0.2, 1.0)),
                "complexity": 0.4 if e.group in ("earnings", "periodic_report") else 0.2,
                "seeding": "official",
                "label": f"{e.form} {', '.join(e.items)}".strip(),
            }
        )
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")


def main(argv: list[str] | None = None) -> dict[str, Any]:
    ap = argparse.ArgumentParser(description="Train on a stock's past events and forecast its later prices.")
    ap.add_argument("ticker", nargs="?", default="AAPL")
    ap.add_argument("--split", default="2024-01-01")
    ap.add_argument("--horizons", default="1,5")
    ap.add_argument("--agents", type=int, default=1500)
    ap.add_argument("--runs", type=int, default=16)
    ap.add_argument("--train-origins", type=int, default=200)
    ap.add_argument("--workers", type=int, default=min(8, max(1, (os.cpu_count() or 2) - 2)))
    ap.add_argument("--quick", action="store_true", help="tiny grid and few origins (smoke test)")
    ap.add_argument("--data-root")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    cfg = ExperimentConfig(
        ticker=args.ticker,
        split=args.split,
        horizons=tuple(int(x) for x in args.horizons.split(",")),
        n_agents=args.agents,
        runs=args.runs,
        train_origins=args.train_origins,
        workers=args.workers,
        data_root=args.data_root,
        out_dir=args.out,
    )
    if args.quick:
        cfg.grid = {"market.noise_frac": [0.6, 1.5]}
        cfg.runs = min(cfg.runs, 4)
        cfg.train_origins = min(cfg.train_origins, 20)
    exp = Experiment(cfg)
    res = exp.run()
    out = Path(cfg.out_dir) if cfg.out_dir else ROOT / "docs" / "experiments" / cfg.ticker.upper()
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(res), encoding="utf-8")
    if not cfg.data_root:
        write_events_json(exp, ROOT / "data" / cfg.ticker.upper() / "events.json")
    from .experiment_report import write_report

    write_report(res, out)
    print(f"wrote {out} in {res['seconds']:.0f}s")
    return res


if __name__ == "__main__":
    main()
